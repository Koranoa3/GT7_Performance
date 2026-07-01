//go:build windows

package main

import (
	"fmt"
	"os"
	"strings"
	"syscall"
	"unsafe"
)

var (
	kernel32            = syscall.NewLazyDLL("kernel32.dll")
	procGetCommState    = kernel32.NewProc("GetCommState")
	procSetCommState    = kernel32.NewProc("SetCommState")
	procSetCommTimeouts = kernel32.NewProc("SetCommTimeouts")
	procPurgeComm       = kernel32.NewProc("PurgeComm")
	procQueryDosDeviceW = kernel32.NewProc("QueryDosDeviceW")
)

const (
	noparity     = 0
	onestopbit   = 0
	purgeTxClear = 0x0004
	purgeRxClear = 0x0008
	maxDWORD     = 0xFFFFFFFF
)

type dcb struct {
	DCBlength  uint32
	BaudRate   uint32
	Flags      uint32
	WReserved  uint16
	XonLim     uint16
	XoffLim    uint16
	ByteSize   byte
	Parity     byte
	StopBits   byte
	XonChar    int8
	XoffChar   int8
	ErrorChar  int8
	EofChar    int8
	EvtChar    int8
	WReserved1 uint16
}

type commTimeouts struct {
	ReadIntervalTimeout         uint32
	ReadTotalTimeoutMultiplier  uint32
	ReadTotalTimeoutConstant    uint32
	WriteTotalTimeoutMultiplier uint32
	WriteTotalTimeoutConstant   uint32
}

type serialPort struct {
	name string
	file *os.File
}

func openSerialPort(name string, baud uint32) (*serialPort, error) {
	path := name
	if !strings.HasPrefix(strings.ToUpper(path), `\\.\`) {
		path = `\\.\` + path
	}
	pathPtr, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}

	handle, err := syscall.CreateFile(
		pathPtr,
		syscall.GENERIC_READ|syscall.GENERIC_WRITE,
		0,
		nil,
		syscall.OPEN_EXISTING,
		0,
		0,
	)
	if err != nil {
		return nil, err
	}

	if err := configureHandle(handle, baud); err != nil {
		_ = syscall.CloseHandle(handle)
		return nil, err
	}

	return &serialPort{
		name: name,
		file: os.NewFile(uintptr(handle), name),
	}, nil
}

func configureHandle(handle syscall.Handle, baud uint32) error {
	state := dcb{DCBlength: uint32(unsafe.Sizeof(dcb{}))}
	ok, _, err := procGetCommState.Call(uintptr(handle), uintptr(unsafe.Pointer(&state)))
	if ok == 0 {
		return fmt.Errorf("GetCommState failed: %w", err)
	}

	state.BaudRate = baud
	state.ByteSize = 8
	state.Parity = noparity
	state.StopBits = onestopbit
	state.Flags |= 0x00000001
	state.Flags &^= 0x00000002

	ok, _, err = procSetCommState.Call(uintptr(handle), uintptr(unsafe.Pointer(&state)))
	if ok == 0 {
		return fmt.Errorf("SetCommState failed: %w", err)
	}

	timeouts := commTimeouts{
		ReadIntervalTimeout:         maxDWORD,
		ReadTotalTimeoutMultiplier:  0,
		ReadTotalTimeoutConstant:    20,
		WriteTotalTimeoutMultiplier: 0,
		WriteTotalTimeoutConstant:   100,
	}
	ok, _, err = procSetCommTimeouts.Call(uintptr(handle), uintptr(unsafe.Pointer(&timeouts)))
	if ok == 0 {
		return fmt.Errorf("SetCommTimeouts failed: %w", err)
	}

	_, _, _ = procPurgeComm.Call(uintptr(handle), uintptr(purgeTxClear|purgeRxClear))
	return nil
}

func listSerialPorts(maxPort int) []string {
	ports := make([]string, 0, maxPort)
	for index := 1; index <= maxPort; index++ {
		name := fmt.Sprintf("COM%d", index)
		if serialPortExists(name) {
			ports = append(ports, name)
		}
	}
	return ports
}

func serialPortExists(name string) bool {
	namePtr, err := syscall.UTF16PtrFromString(name)
	if err != nil {
		return false
	}

	buffer := make([]uint16, 512)
	result, _, _ := procQueryDosDeviceW.Call(
		uintptr(unsafe.Pointer(namePtr)),
		uintptr(unsafe.Pointer(&buffer[0])),
		uintptr(len(buffer)),
	)
	return result != 0
}

func (p *serialPort) Read(buffer []byte) (int, error) {
	return p.file.Read(buffer)
}

func (p *serialPort) Write(buffer []byte) (int, error) {
	return p.file.Write(buffer)
}

func (p *serialPort) Close() error {
	return p.file.Close()
}
