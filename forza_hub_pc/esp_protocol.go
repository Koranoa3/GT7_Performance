package main

import (
	"encoding/binary"
	"errors"
	"math"
	"net"
)

const (
	espMagic0          = 'G'
	espMagic1          = '7'
	espProtocolVersion = 1
	espHeaderSize      = 12
	espMaxPayloadSize  = 96
	espMaxFrameSize    = 128

	frameTypePing           = 1
	frameTypePong           = 2
	frameTypeTelemetry      = 3
	frameTypeBind           = 4
	frameTypeEvent          = 5
	frameTypeAck            = 6
	frameTypeSectionPreview = 7

	eventCollision = 1
	eventLap       = 2
)

type espFrame struct {
	Type       uint8
	Flags      uint8
	Seq        uint16
	DeviceID   uint16
	Payload    []byte
	PayloadLen uint16
}

type espTelemetryPayload struct {
	CarSpeed      float32
	EngineRPM     float32
	RPMAlertMin   float32
	RPMAlertMax   float32
	Throttle      uint8
	Brake         uint8
	CurrentGear   int8
	VelocityRight float32
	PlayState     uint8
}

type frameParser struct {
	buffer []byte
}

func (p *frameParser) push(data []byte) {
	if len(data) == 0 {
		return
	}
	p.buffer = append(p.buffer, data...)
	if len(p.buffer) > 8*espMaxFrameSize {
		p.buffer = append([]byte(nil), p.buffer[len(p.buffer)-4*espMaxFrameSize:]...)
	}
}

func (p *frameParser) pop() (espFrame, bool) {
	for len(p.buffer) >= espHeaderSize {
		if p.buffer[0] != espMagic0 || p.buffer[1] != espMagic1 {
			p.buffer = p.buffer[1:]
			continue
		}

		if p.buffer[2] != espProtocolVersion {
			p.buffer = p.buffer[espHeaderSize:]
			continue
		}

		payloadLen := binary.LittleEndian.Uint16(p.buffer[10:12])
		if payloadLen > espMaxPayloadSize {
			p.buffer = p.buffer[2:]
			continue
		}

		frameLen := espHeaderSize + int(payloadLen)
		if len(p.buffer) < frameLen {
			return espFrame{}, false
		}

		frame := espFrame{
			Type:       p.buffer[3],
			Flags:      p.buffer[4],
			Seq:        binary.LittleEndian.Uint16(p.buffer[6:8]),
			DeviceID:   binary.LittleEndian.Uint16(p.buffer[8:10]),
			PayloadLen: payloadLen,
		}
		if payloadLen > 0 {
			frame.Payload = append([]byte(nil), p.buffer[espHeaderSize:frameLen]...)
		}
		p.buffer = p.buffer[frameLen:]
		return frame, true
	}

	return espFrame{}, false
}

func buildFrame(frameType uint8, deviceID uint16, seq uint16, payload []byte) ([]byte, error) {
	if len(payload) > espMaxPayloadSize {
		return nil, errors.New("payload too large for ESP frame")
	}

	frame := make([]byte, espHeaderSize+len(payload))
	frame[0] = espMagic0
	frame[1] = espMagic1
	frame[2] = espProtocolVersion
	frame[3] = frameType
	frame[4] = 0
	frame[5] = 0
	binary.LittleEndian.PutUint16(frame[6:8], seq)
	binary.LittleEndian.PutUint16(frame[8:10], deviceID)
	binary.LittleEndian.PutUint16(frame[10:12], uint16(len(payload)))
	copy(frame[espHeaderSize:], payload)
	return frame, nil
}

func buildBindPayload(ip net.IP) ([]byte, error) {
	ip4 := ip.To4()
	if ip4 == nil {
		return nil, errors.New("bind payload requires IPv4 address")
	}
	return append([]byte(nil), ip4...), nil
}

func buildEventPayload(eventID uint8, value uint8) []byte {
	return []byte{eventID, value}
}

func buildTelemetryPayload(payload espTelemetryPayload) []byte {
	buf := make([]byte, 24)
	binary.LittleEndian.PutUint32(buf[0:4], math.Float32bits(payload.CarSpeed))
	binary.LittleEndian.PutUint32(buf[4:8], math.Float32bits(payload.EngineRPM))
	binary.LittleEndian.PutUint32(buf[8:12], math.Float32bits(payload.RPMAlertMin))
	binary.LittleEndian.PutUint32(buf[12:16], math.Float32bits(payload.RPMAlertMax))
	buf[16] = payload.Throttle
	buf[17] = payload.Brake
	buf[18] = byte(payload.CurrentGear)
	binary.LittleEndian.PutUint32(buf[19:23], math.Float32bits(payload.VelocityRight))
	buf[23] = payload.PlayState
	return buf
}
