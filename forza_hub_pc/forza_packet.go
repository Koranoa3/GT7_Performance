package main

import (
	"encoding/binary"
	"fmt"
	"math"
)

const forzaPacketSize = 324

type vec3 struct {
	X float32
	Y float32
	Z float32
}

type wheelFloats struct {
	FrontLeft  float32
	FrontRight float32
	RearLeft   float32
	RearRight  float32
}

type wheelInts struct {
	FrontLeft  int32
	FrontRight int32
	RearLeft   int32
	RearRight  int32
}

type wheelTemps struct {
	FrontLeft  float32
	FrontRight float32
	RearLeft   float32
	RearRight  float32
}

type forzaTelemetry struct {
	IsRaceOn                    int32
	TimestampMS                 uint32
	EngineMaxRpm                float32
	EngineIdleRpm               float32
	CurrentEngineRpm            float32
	Acceleration                vec3
	Velocity                    vec3
	AngularVelocity             vec3
	Orientation                 vec3
	SuspensionTravel            wheelFloats
	TireSlipRatio               wheelFloats
	WheelRotationSpeed          wheelFloats
	WheelOnRumbleStrip          wheelInts
	WheelInPuddle               wheelInts
	SurfaceRumble               wheelFloats
	TireSlipAngle               wheelFloats
	TireCombinedSlip            wheelFloats
	SuspensionMeters            wheelFloats
	CarOrdinal                  int32
	CarClass                    int32
	CarPerformanceIndex         int32
	DrivetrainType              int32
	NumCylinders                int32
	CarGroup                    uint32
	SmashableVelDiff            float32
	SmashableMass               float32
	Position                    vec3
	Speed                       float32
	Power                       float32
	Torque                      float32
	TireTemp                    wheelTemps
	Boost                       float32
	Fuel                        float32
	DistanceTraveled            float32
	BestLap                     float32
	LastLap                     float32
	CurrentLap                  float32
	CurrentRaceTime             float32
	LapNumber                   uint16
	RacePosition                uint8
	Accel                       uint8
	Brake                       uint8
	Clutch                      uint8
	HandBrake                   uint8
	Gear                        uint8
	Steer                       int8
	NormalizedDrivingLine       int8
	NormalizedAIBrakeDifference int8
}

type packetReader struct {
	data   []byte
	offset int
}

func parseForzaTelemetry(data []byte) (forzaTelemetry, error) {
	if len(data) != forzaPacketSize {
		return forzaTelemetry{}, fmt.Errorf("unexpected packet size %d", len(data))
	}

	r := &packetReader{data: data}
	packet := forzaTelemetry{
		IsRaceOn:                    r.s32(),
		TimestampMS:                 r.u32(),
		EngineMaxRpm:                r.f32(),
		EngineIdleRpm:               r.f32(),
		CurrentEngineRpm:            r.f32(),
		Acceleration:                vec3{r.f32(), r.f32(), r.f32()},
		Velocity:                    vec3{r.f32(), r.f32(), r.f32()},
		AngularVelocity:             vec3{r.f32(), r.f32(), r.f32()},
		Orientation:                 vec3{r.f32(), r.f32(), r.f32()},
		SuspensionTravel:            wheelFloats{r.f32(), r.f32(), r.f32(), r.f32()},
		TireSlipRatio:               wheelFloats{r.f32(), r.f32(), r.f32(), r.f32()},
		WheelRotationSpeed:          wheelFloats{r.f32(), r.f32(), r.f32(), r.f32()},
		WheelOnRumbleStrip:          wheelInts{r.s32(), r.s32(), r.s32(), r.s32()},
		WheelInPuddle:               wheelInts{r.s32(), r.s32(), r.s32(), r.s32()},
		SurfaceRumble:               wheelFloats{r.f32(), r.f32(), r.f32(), r.f32()},
		TireSlipAngle:               wheelFloats{r.f32(), r.f32(), r.f32(), r.f32()},
		TireCombinedSlip:            wheelFloats{r.f32(), r.f32(), r.f32(), r.f32()},
		SuspensionMeters:            wheelFloats{r.f32(), r.f32(), r.f32(), r.f32()},
		CarOrdinal:                  r.s32(),
		CarClass:                    r.s32(),
		CarPerformanceIndex:         r.s32(),
		DrivetrainType:              r.s32(),
		NumCylinders:                r.s32(),
		CarGroup:                    r.u32(),
		SmashableVelDiff:            r.f32(),
		SmashableMass:               r.f32(),
		Position:                    vec3{r.f32(), r.f32(), r.f32()},
		Speed:                       r.f32(),
		Power:                       r.f32(),
		Torque:                      r.f32(),
		TireTemp:                    wheelTemps{r.f32(), r.f32(), r.f32(), r.f32()},
		Boost:                       r.f32(),
		Fuel:                        r.f32(),
		DistanceTraveled:            r.f32(),
		BestLap:                     r.f32(),
		LastLap:                     r.f32(),
		CurrentLap:                  r.f32(),
		CurrentRaceTime:             r.f32(),
		LapNumber:                   r.u16(),
		RacePosition:                r.u8(),
		Accel:                       r.u8(),
		Brake:                       r.u8(),
		Clutch:                      r.u8(),
		HandBrake:                   r.u8(),
		Gear:                        r.u8(),
		Steer:                       r.s8(),
		NormalizedDrivingLine:       r.s8(),
		NormalizedAIBrakeDifference: r.s8(),
	}

	if r.offset != len(data) {
		return forzaTelemetry{}, fmt.Errorf("packet parse ended at %d, expected %d", r.offset, len(data))
	}

	return packet, nil
}

func (r *packetReader) f32() float32 {
	value := math.Float32frombits(binary.LittleEndian.Uint32(r.data[r.offset : r.offset+4]))
	r.offset += 4
	return value
}

func (r *packetReader) s32() int32 {
	value := int32(binary.LittleEndian.Uint32(r.data[r.offset : r.offset+4]))
	r.offset += 4
	return value
}

func (r *packetReader) u32() uint32 {
	value := binary.LittleEndian.Uint32(r.data[r.offset : r.offset+4])
	r.offset += 4
	return value
}

func (r *packetReader) u16() uint16 {
	value := binary.LittleEndian.Uint16(r.data[r.offset : r.offset+2])
	r.offset += 2
	return value
}

func (r *packetReader) u8() uint8 {
	value := r.data[r.offset]
	r.offset++
	return value
}

func (r *packetReader) s8() int8 {
	value := int8(r.data[r.offset])
	r.offset++
	return value
}

func (p forzaTelemetry) maxAbsAcceleration() float32 {
	maxValue := abs32(p.Acceleration.X)
	if value := abs32(p.Acceleration.Y); value > maxValue {
		maxValue = value
	}
	if value := abs32(p.Acceleration.Z); value > maxValue {
		maxValue = value
	}
	return maxValue
}

func abs32(value float32) float32 {
	if value < 0 {
		return -value
	}
	return value
}
