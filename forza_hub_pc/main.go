package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"math"
	"net"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

const (
	defaultListenAddr        = "0.0.0.0:12350"
	defaultESPBaud           = 115200
	defaultTelemetryRateHz   = 20.0
	defaultIdleRateHz        = 5.0
	defaultTelemetryFresh    = 350 * time.Millisecond
	defaultScanInterval      = 1200 * time.Millisecond
	defaultProbeTimeout      = 1500 * time.Millisecond
	defaultLinkTimeout       = 3500 * time.Millisecond
	defaultPingInterval      = 1000 * time.Millisecond
	defaultBindRetry         = 1200 * time.Millisecond
	defaultCollisionThresh   = 18.0
	defaultCollisionCeil     = 60.0
	defaultCollisionCooldown = 900 * time.Millisecond
	defaultRpmAlertRatio     = 0.85
)

type config struct {
	ListenAddr         string
	ESPPort            string
	ESPBaud            int
	MaxCOM             int
	TelemetryRateHz    float64
	IdleRateHz         float64
	TelemetryFresh     time.Duration
	ScanInterval       time.Duration
	ProbeTimeout       time.Duration
	LinkTimeout        time.Duration
	PingInterval       time.Duration
	BindRetry          time.Duration
	CollisionThreshold float64
	CollisionCeiling   float64
	CollisionCooldown  time.Duration
	RPMAlertRatio      float64
	BindIP             string
	ZeroGearNeutral    bool
}

type telemetrySample struct {
	Packet     forzaTelemetry
	ReceivedAt time.Time
	SourceIP   net.IP
}

type pendingEvent struct {
	ID    uint8
	Value uint8
}

type app struct {
	cfg config

	udpConn      *net.UDPConn
	telemetryCh  chan telemetrySample
	latest       telemetrySample
	hasTelemetry bool
	packetCount  uint64
	invalidCount uint64

	lastLapNumber          uint16
	hasLapReference        bool
	lastCollisionTriggered time.Time

	serial            *serialPort
	serialParser      frameParser
	activePortName    string
	serialOpenedAt    time.Time
	portCooldownUntil map[string]time.Time
	lastScanAt        time.Time

	espID             uint16
	nextSeq           uint16
	lastESPSeenAt     time.Time
	lastPCPingAt      time.Time
	lastBindSentAt    time.Time
	lastBindIP        string
	bindConfirmed     bool
	lastTelemetryTxAt time.Time
	lastIdleTxAt      time.Time
	lastSentTimestamp uint32

	pendingEvents []pendingEvent
}

func main() {
	cfg := loadConfig()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	application, err := newApp(cfg)
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to initialize app: %v\n", err)
		os.Exit(1)
	}
	defer application.close()

	if err := application.run(ctx); err != nil && !errors.Is(err, context.Canceled) {
		fmt.Fprintf(os.Stderr, "\napplication stopped with error: %v\n", err)
		os.Exit(1)
	}

	fmt.Println()
}

func loadConfig() config {
	cfg := config{}
	flag.StringVar(&cfg.ListenAddr, "listen", defaultListenAddr, "UDP listen address for Forza Data Out, for example 0.0.0.0:12350")
	flag.StringVar(&cfg.ESPPort, "esp-port", "", "fixed ESP COM port, for example COM4; leave empty for auto scan")
	flag.IntVar(&cfg.ESPBaud, "esp-baud", defaultESPBaud, "ESP32 serial baud rate")
	flag.IntVar(&cfg.MaxCOM, "scan-max-com", 32, "maximum COM index to probe during auto scan")
	flag.Float64Var(&cfg.TelemetryRateHz, "telemetry-rate", defaultTelemetryRateHz, "maximum ESP telemetry send rate in Hz")
	flag.Float64Var(&cfg.IdleRateHz, "idle-rate", defaultIdleRateHz, "synthetic idle telemetry send rate in Hz when Forza is not actively sending")
	flag.DurationVar(&cfg.TelemetryFresh, "telemetry-fresh", defaultTelemetryFresh, "how long a Forza packet stays fresh enough to be treated as play_state=1")
	flag.DurationVar(&cfg.ScanInterval, "scan-interval", defaultScanInterval, "interval between ESP scan attempts")
	flag.DurationVar(&cfg.ProbeTimeout, "probe-timeout", defaultProbeTimeout, "how long to wait for ESP ping after opening a candidate COM port")
	flag.DurationVar(&cfg.LinkTimeout, "link-timeout", defaultLinkTimeout, "how long to wait before treating the active ESP link as disconnected")
	flag.DurationVar(&cfg.PingInterval, "ping-interval", defaultPingInterval, "interval for PC-originated ESP ping keepalive")
	flag.DurationVar(&cfg.BindRetry, "bind-retry", defaultBindRetry, "interval before resending bind while ACK is not confirmed")
	flag.Float64Var(&cfg.CollisionThreshold, "collision-threshold", defaultCollisionThresh, "absolute acceleration threshold that starts a collision event")
	flag.Float64Var(&cfg.CollisionCeiling, "collision-ceiling", defaultCollisionCeil, "absolute acceleration that maps to max collision strength")
	flag.DurationVar(&cfg.CollisionCooldown, "collision-cooldown", defaultCollisionCooldown, "minimum interval between collision events")
	flag.Float64Var(&cfg.RPMAlertRatio, "rpm-alert-ratio", defaultRpmAlertRatio, "ratio of engine max RPM used as the ESP shift-alert threshold")
	flag.StringVar(&cfg.BindIP, "bind-ip", "", "override IPv4 value sent in BIND; defaults to telemetry sender IP or 127.0.0.1")
	flag.BoolVar(&cfg.ZeroGearNeutral, "zero-gear-neutral", true, "map Forza gear 0 to ESP neutral (-1) instead of forwarding 0")
	flag.Parse()

	if cfg.TelemetryRateHz <= 0 {
		cfg.TelemetryRateHz = defaultTelemetryRateHz
	}
	if cfg.IdleRateHz <= 0 {
		cfg.IdleRateHz = defaultIdleRateHz
	}
	if cfg.MaxCOM <= 0 {
		cfg.MaxCOM = 32
	}
	if cfg.RPMAlertRatio <= 0 || cfg.RPMAlertRatio > 1 {
		cfg.RPMAlertRatio = defaultRpmAlertRatio
	}
	if cfg.CollisionCeiling <= cfg.CollisionThreshold {
		cfg.CollisionCeiling = cfg.CollisionThreshold + 1
	}

	return cfg
}

func newApp(cfg config) (*app, error) {
	udpAddr, err := net.ResolveUDPAddr("udp", cfg.ListenAddr)
	if err != nil {
		return nil, fmt.Errorf("resolve UDP listen address: %w", err)
	}

	conn, err := net.ListenUDP("udp", udpAddr)
	if err != nil {
		return nil, fmt.Errorf("listen UDP: %w", err)
	}

	return &app{
		cfg:               cfg,
		udpConn:           conn,
		telemetryCh:       make(chan telemetrySample, 128),
		nextSeq:           1,
		portCooldownUntil: make(map[string]time.Time),
	}, nil
}

func (a *app) close() {
	if a.serial != nil {
		_ = a.serial.Close()
		a.serial = nil
	}
	if a.udpConn != nil {
		_ = a.udpConn.Close()
		a.udpConn = nil
	}
}

func (a *app) run(ctx context.Context) error {
	go a.receiveForzaTelemetry(ctx)

	workTicker := time.NewTicker(20 * time.Millisecond)
	defer workTicker.Stop()
	statusTicker := time.NewTicker(250 * time.Millisecond)
	defer statusTicker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case sample := <-a.telemetryCh:
			a.handleTelemetrySample(sample)
			a.drainTelemetryChannel()
		case <-workTicker.C:
			a.drainTelemetryChannel()
			a.tick(time.Now())
		case <-statusTicker.C:
			a.renderStatus(time.Now())
		}
	}
}

func (a *app) receiveForzaTelemetry(ctx context.Context) {
	buffer := make([]byte, 2048)
	for {
		_ = a.udpConn.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
		n, addr, err := a.udpConn.ReadFromUDP(buffer)
		if err != nil {
			if ne, ok := err.(net.Error); ok && ne.Timeout() {
				select {
				case <-ctx.Done():
					return
				default:
					continue
				}
			}
			select {
			case <-ctx.Done():
				return
			default:
				continue
			}
		}

		packet, err := parseForzaTelemetry(buffer[:n])
		if err != nil {
			a.invalidCount++
			continue
		}

		sample := telemetrySample{
			Packet:     packet,
			ReceivedAt: time.Now(),
			SourceIP:   append(net.IP(nil), addr.IP...),
		}

		select {
		case a.telemetryCh <- sample:
		default:
			select {
			case <-a.telemetryCh:
			default:
			}
			a.telemetryCh <- sample
		}
	}
}

func (a *app) drainTelemetryChannel() {
	for {
		select {
		case sample := <-a.telemetryCh:
			a.handleTelemetrySample(sample)
		default:
			return
		}
	}
}

func (a *app) handleTelemetrySample(sample telemetrySample) {
	a.latest = sample
	a.hasTelemetry = true
	a.packetCount++

	if a.hasLapReference {
		if sample.Packet.LapNumber > a.lastLapNumber {
			a.pendingEvents = append(a.pendingEvents, pendingEvent{
				ID:    eventLap,
				Value: uint8(minInt(int(sample.Packet.LapNumber), 255)),
			})
		}
	}
	a.lastLapNumber = sample.Packet.LapNumber
	a.hasLapReference = true

	maxAbsAcceleration := float64(sample.Packet.maxAbsAcceleration())
	if maxAbsAcceleration >= a.cfg.CollisionThreshold && sample.ReceivedAt.Sub(a.lastCollisionTriggered) >= a.cfg.CollisionCooldown {
		a.pendingEvents = append(a.pendingEvents, pendingEvent{
			ID:    eventCollision,
			Value: scaleCollisionStrength(maxAbsAcceleration, a.cfg.CollisionThreshold, a.cfg.CollisionCeiling),
		})
		a.lastCollisionTriggered = sample.ReceivedAt
	}

	if a.serial != nil && a.espID != 0 {
		desiredIP := a.desiredBindIP()
		if desiredIP.String() != a.lastBindIP {
			_ = a.sendBind(desiredIP)
		}
	}
}

func (a *app) tick(now time.Time) {
	if a.serial == nil {
		a.scanForESP(now)
		return
	}

	if err := a.pollSerial(now); err != nil {
		a.disconnect(fmt.Sprintf("serial read failed: %v", err), 3*time.Second)
		return
	}

	if a.espID == 0 {
		if now.Sub(a.serialOpenedAt) > a.cfg.ProbeTimeout {
			a.disconnect("probe timed out without ESP ping", 8*time.Second)
		}
		return
	}

	if now.Sub(a.lastESPSeenAt) > a.cfg.LinkTimeout {
		a.disconnect("active ESP timed out", 2*time.Second)
		return
	}

	if now.Sub(a.lastPCPingAt) >= a.cfg.PingInterval {
		if err := a.sendFrame(frameTypePing, nil); err != nil {
			a.disconnect(fmt.Sprintf("PC ping failed: %v", err), 2*time.Second)
			return
		}
		a.lastPCPingAt = now
	}

	desiredBindIP := a.desiredBindIP()
	if !a.bindConfirmed && now.Sub(a.lastBindSentAt) >= a.cfg.BindRetry {
		if err := a.sendBind(desiredBindIP); err != nil {
			a.disconnect(fmt.Sprintf("bind retry failed: %v", err), 2*time.Second)
			return
		}
	}

	if len(a.pendingEvents) > 0 && a.bindConfirmed {
		if err := a.flushPendingEvents(); err != nil {
			a.disconnect(fmt.Sprintf("event send failed: %v", err), 2*time.Second)
			return
		}
	}

	if err := a.maybeSendTelemetry(now); err != nil {
		a.disconnect(fmt.Sprintf("telemetry send failed: %v", err), 2*time.Second)
	}
}

func (a *app) scanForESP(now time.Time) {
	if now.Sub(a.lastScanAt) < a.cfg.ScanInterval {
		return
	}
	a.lastScanAt = now

	var candidates []string
	if strings.TrimSpace(a.cfg.ESPPort) != "" {
		candidates = []string{strings.TrimSpace(a.cfg.ESPPort)}
	} else {
		candidates = listSerialPorts(a.cfg.MaxCOM)
	}

	for _, portName := range candidates {
		if cooldownUntil, ok := a.portCooldownUntil[portName]; ok && now.Before(cooldownUntil) {
			continue
		}

		port, err := openSerialPort(portName, uint32(a.cfg.ESPBaud))
		if err != nil {
			a.portCooldownUntil[portName] = now.Add(2 * time.Second)
			continue
		}

		a.serial = port
		a.activePortName = portName
		a.serialOpenedAt = now
		a.serialParser = frameParser{}
		a.espID = 0
		a.bindConfirmed = false
		a.lastBindIP = ""
		a.lastBindSentAt = time.Time{}
		a.lastESPSeenAt = now
		a.lastPCPingAt = time.Time{}
		a.lastTelemetryTxAt = time.Time{}
		a.lastIdleTxAt = time.Time{}
		a.lastSentTimestamp = 0
		a.pendingEvents = a.pendingEvents[:0]
		return
	}
}

func (a *app) pollSerial(now time.Time) error {
	buffer := make([]byte, 256)
	for readCount := 0; readCount < 8; readCount++ {
		n, err := a.serial.Read(buffer)
		if err != nil {
			return err
		}
		if n == 0 {
			return nil
		}
		a.serialParser.push(buffer[:n])

		for {
			frame, ok := a.serialParser.pop()
			if !ok {
				break
			}
			a.handleESPFrame(frame, now)
		}
	}
	return nil
}

func (a *app) handleESPFrame(frame espFrame, now time.Time) {
	a.lastESPSeenAt = now
	switch frame.Type {
	case frameTypePing:
		a.espID = frame.DeviceID
		_ = a.sendFrame(frameTypePong, nil)
		desiredIP := a.desiredBindIP()
		if !a.bindConfirmed || desiredIP.String() != a.lastBindIP {
			_ = a.sendBind(desiredIP)
		}
	case frameTypePong:
		a.espID = frame.DeviceID
	case frameTypeAck:
		if a.espID == 0 {
			a.espID = frame.DeviceID
		}
		a.bindConfirmed = true
	default:
	}
}

func (a *app) flushPendingEvents() error {
	for len(a.pendingEvents) > 0 {
		event := a.pendingEvents[0]
		payload := buildEventPayload(event.ID, event.Value)
		if err := a.sendFrame(frameTypeEvent, payload); err != nil {
			return err
		}
		a.pendingEvents = a.pendingEvents[1:]
	}
	return nil
}

func (a *app) maybeSendTelemetry(now time.Time) error {
	if a.espID == 0 || !a.bindConfirmed {
		return nil
	}

	live := a.hasTelemetry && now.Sub(a.latest.ReceivedAt) <= a.cfg.TelemetryFresh
	if live {
		if a.latest.Packet.TimestampMS == a.lastSentTimestamp {
			return nil
		}
		if now.Sub(a.lastTelemetryTxAt) < hzInterval(a.cfg.TelemetryRateHz) {
			return nil
		}

		payload := a.telemetryPayloadForPacket(a.latest.Packet, 1)
		if err := a.sendFrame(frameTypeTelemetry, buildTelemetryPayload(payload)); err != nil {
			return err
		}
		a.lastTelemetryTxAt = now
		a.lastSentTimestamp = a.latest.Packet.TimestampMS
		return nil
	}

	if now.Sub(a.lastIdleTxAt) < hzInterval(a.cfg.IdleRateHz) {
		return nil
	}

	var idlePayload espTelemetryPayload
	if a.hasTelemetry {
		idlePayload = a.telemetryPayloadForPacket(a.latest.Packet, 0)
		idlePayload.CarSpeed = 0
		idlePayload.EngineRPM = 0
		idlePayload.Throttle = 0
		idlePayload.Brake = 0
		idlePayload.VelocityRight = 0
		idlePayload.CurrentGear = -1
	} else {
		idlePayload = espTelemetryPayload{CurrentGear: -1, PlayState: 0}
	}

	if err := a.sendFrame(frameTypeTelemetry, buildTelemetryPayload(idlePayload)); err != nil {
		return err
	}
	a.lastIdleTxAt = now
	return nil
}

func (a *app) telemetryPayloadForPacket(packet forzaTelemetry, playState uint8) espTelemetryPayload {
	alertMin := packet.EngineMaxRpm * float32(a.cfg.RPMAlertRatio)
	if alertMin < packet.EngineIdleRpm {
		alertMin = packet.EngineIdleRpm
	}
	alertMax := packet.EngineMaxRpm
	if alertMax < alertMin {
		alertMax = alertMin
	}

	currentGear := int8(packet.Gear)
	if a.cfg.ZeroGearNeutral && packet.Gear == 0 {
		currentGear = -1
	}

	return espTelemetryPayload{
		CarSpeed:      packet.Speed,
		EngineRPM:     packet.CurrentEngineRpm,
		RPMAlertMin:   alertMin,
		RPMAlertMax:   alertMax,
		Throttle:      packet.Accel,
		Brake:         packet.Brake,
		CurrentGear:   currentGear,
		VelocityRight: packet.Velocity.X,
		PlayState:     playState,
	}
}

func (a *app) sendBind(ip net.IP) error {
	payload, err := buildBindPayload(ip)
	if err != nil {
		return err
	}
	if err := a.sendFrame(frameTypeBind, payload); err != nil {
		return err
	}
	a.lastBindSentAt = time.Now()
	a.lastBindIP = ip.String()
	return nil
}

func (a *app) sendFrame(frameType uint8, payload []byte) error {
	if a.serial == nil {
		return errors.New("serial port is not open")
	}
	frame, err := buildFrame(frameType, a.espID, a.nextSeq, payload)
	if err != nil {
		return err
	}
	a.nextSeq++
	_, err = a.serial.Write(frame)
	return err
}

func (a *app) disconnect(reason string, cooldown time.Duration) {
	if a.serial != nil {
		_ = a.serial.Close()
	}
	if a.activePortName != "" {
		a.portCooldownUntil[a.activePortName] = time.Now().Add(cooldown)
	}
	a.serial = nil
	a.serialParser = frameParser{}
	a.activePortName = ""
	a.serialOpenedAt = time.Time{}
	a.espID = 0
	a.bindConfirmed = false
	a.lastBindIP = ""
	a.lastBindSentAt = time.Time{}
	a.lastESPSeenAt = time.Time{}
	a.lastPCPingAt = time.Time{}
	a.lastTelemetryTxAt = time.Time{}
	a.lastIdleTxAt = time.Time{}
	a.lastSentTimestamp = 0
	a.pendingEvents = a.pendingEvents[:0]
	_ = reason
}

func (a *app) desiredBindIP() net.IP {
	if strings.TrimSpace(a.cfg.BindIP) != "" {
		if parsed := net.ParseIP(strings.TrimSpace(a.cfg.BindIP)); parsed != nil {
			return parsed.To4()
		}
	}
	if a.hasTelemetry {
		if ip := a.latest.SourceIP.To4(); ip != nil {
			return ip
		}
	}
	return net.IPv4(127, 0, 0, 1)
}

func (a *app) renderStatus(now time.Time) {
	forzaState := "waiting"
	if a.hasTelemetry {
		age := now.Sub(a.latest.ReceivedAt)
		if age <= a.cfg.TelemetryFresh {
			forzaState = fmt.Sprintf("receiving %s age=%dms speed=%.1f lap=%d",
				a.latest.SourceIP.String(),
				age.Milliseconds(),
				a.latest.Packet.Speed,
				a.latest.Packet.LapNumber,
			)
		} else {
			forzaState = fmt.Sprintf("idle age=%dms last=%s",
				age.Milliseconds(),
				a.latest.SourceIP.String(),
			)
		}
	}

	espState := "scanning"
	if a.serial != nil {
		if a.espID == 0 {
			espState = fmt.Sprintf("probing %s", a.activePortName)
		} else {
			age := now.Sub(a.lastESPSeenAt).Milliseconds()
			espState = fmt.Sprintf("connected %s id=%d bind=%t age=%dms ip=%s",
				a.activePortName,
				a.espID,
				a.bindConfirmed,
				age,
				a.lastBindIP,
			)
		}
	}

	line := fmt.Sprintf(
		"Forza[%s packets=%d invalid=%d]  ESP[%s]",
		forzaState,
		a.packetCount,
		a.invalidCount,
		espState,
	)
	fmt.Printf("\r%-180s", line)
}

func hzInterval(rate float64) time.Duration {
	if rate <= 0 {
		return 0
	}
	return time.Duration(float64(time.Second) / rate)
}

func scaleCollisionStrength(value float64, threshold float64, ceiling float64) uint8 {
	if value <= threshold {
		return 0
	}
	ratio := (value - threshold) / (ceiling - threshold)
	if ratio < 0 {
		ratio = 0
	}
	if ratio > 1 {
		ratio = 1
	}
	scaled := int(math.Round(ratio * 255))
	if scaled < 1 {
		scaled = 1
	}
	if scaled > 255 {
		scaled = 255
	}
	return uint8(scaled)
}

func minInt(left int, right int) int {
	if left < right {
		return left
	}
	return right
}
