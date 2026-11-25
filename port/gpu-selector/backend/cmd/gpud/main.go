// SPDX-License-Identifier: Apache-2.0
// System-only Android init service. Verifies the Pixel 2 card before opening the vendor slot or boot-control sector.
package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"runtime/debug"
	"strconv"
	"strings"
	"syscall"
	"time"

	"pixel2/gpu/profile"
	"pixel2/gpu/slot"
)

type partition struct {
	label                  string
	number, first, sectors int
}

var controlPart = partition{"misc", 5, 319488, 8192}
var vendorPart = partition{"backup", 10, 641024, 761856}

var wrongBoard = errors.New("unrecognized Pixel 2 boot card")

func value(path string) string { b, _ := os.ReadFile(path); return strings.TrimSpace(string(b)) }
func active() string {
	for _, arg := range strings.Fields(value("/proc/cmdline")) {
		switch arg {
		case "androidboot.pixel2gpu=trial":
			return "trial"
		case "androidboot.pixel2gpu=kept":
			return "kept"
		case "androidboot.pixel2gpu=forced":
			return "forced"
		case "androidboot.pixel2gpu=mesa":
			return "mesa"
		}
	}
	return "unknown"
}
func openPart(part partition, writable bool) (*os.File, error) {
	target, e := filepath.EvalSymlinks("/dev/block/by-name/" + part.label)
	if e != nil {
		return nil, wrongBoard
	}
	name := filepath.Base(target)
	sys := "/sys/class/block/" + name
	parent := ""
	switch name {
	case "mmcblk0p" + strconv.Itoa(part.number):
		parent = "mmcblk0"
		if value("/sys/class/block/mmcblk0/device/type") != "SD" {
			return nil, wrongBoard
		}
	case "vda" + strconv.Itoa(part.number):
		parent = "vda"
		m, _ := os.ReadFile("/proc/device-tree/compatible")
		if !bytes.Contains(m, []byte("linux,dummy-virt\x00")) {
			return nil, wrongBoard
		}
	default:
		return nil, wrongBoard
	}
	if value(sys+"/partition") != strconv.Itoa(part.number) || value(sys+"/start") != strconv.Itoa(part.first) || value(sys+"/size") != strconv.Itoa(part.sectors) {
		return nil, wrongBoard
	}
	disk, e := os.Open("/dev/block/" + parent)
	if e != nil {
		return nil, e
	}
	var head [512]byte
	_, e = disk.ReadAt(head[:], 512)
	if e != nil {
		disk.Close()
		return nil, e
	}
	guid := []byte{0x30, 0xd8, 0xe4, 0x10, 0x2a, 0x2e, 0x9a, 0x40, 0xb6, 0x41, 0xc9, 0xcc, 0xd8, 0x06, 0x74, 0x4c}
	if string(head[:8]) != "EFI PART" || !bytes.Equal(head[56:72], guid) || binary.LittleEndian.Uint64(head[72:]) != 2 || binary.LittleEndian.Uint32(head[84:]) != 128 {
		disk.Close()
		return nil, wrongBoard
	}
	var ent [128]byte
	_, e = disk.ReadAt(ent[:], 1024+int64(part.number-1)*128)
	disk.Close()
	var label [72]byte
	for i := range part.label {
		label[2*i] = part.label[i]
	}
	if e != nil || binary.LittleEndian.Uint64(ent[32:]) != uint64(part.first) || binary.LittleEndian.Uint64(ent[40:]) != uint64(part.first+part.sectors-1) || !bytes.Equal(ent[56:], label[:]) {
		return nil, wrongBoard
	}
	flags := os.O_RDONLY
	if writable {
		flags = os.O_RDWR
	}
	f, e := os.OpenFile(target, flags|syscall.O_NOFOLLOW, 0)
	if e != nil {
		return nil, e
	}
	var st syscall.Stat_t
	if syscall.Fstat(int(f.Fd()), &st) != nil || st.Mode&syscall.S_IFMT != syscall.S_IFBLK {
		f.Close()
		return nil, wrongBoard
	}
	maj := ((st.Rdev >> 8) & 4095) | ((st.Rdev >> 32) & 0xfffff000)
	minor := (st.Rdev & 255) | ((st.Rdev >> 12) & 0xffffff00)
	if value(sys+"/dev") != fmt.Sprintf("%d:%d", maj, minor) {
		f.Close()
		return nil, wrongBoard
	}
	lock := syscall.LOCK_SH
	if writable {
		lock = syscall.LOCK_EX
	}
	if e = syscall.Flock(int(f.Fd()), lock); e != nil {
		f.Close()
		return nil, e
	}
	return f, nil
}
func peerSystem(c *net.UnixConn) bool {
	raw, e := c.SyscallConn()
	if e != nil {
		return false
	}
	ok := false
	e = raw.Control(func(fd uintptr) {
		cred, e := syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
		ok = e == nil && cred.Uid == 1000
	})
	return e == nil && ok
}

type reply struct {
	OK     bool   `json:"ok"`
	State  uint32 `json:"state"`
	Active string `json:"active"`
	Error  string `json:"error,omitempty"`
}

func operate(op byte, fd int) (r reply) {
	r.Active = active()
	r.State = slot.Invalid
	if r.Active == "unknown" {
		r.Error = "board"
		return
	}
	if !strings.ContainsRune("SITMKA", rune(op)) {
		r.Error = "request"
		return
	}
	control, e := openPart(controlPart, op != 'S')
	if e != nil {
		r.Error = "board"
		return
	}
	defer control.Close()
	var vendor *os.File
	if op == 'I' || op == 'T' {
		if (op == 'T' && r.Active != "mesa") || (op == 'I' && r.Active != "mesa" && r.Active != "forced") {
			r.Error = "state"
			return
		}
		vendor, e = openPart(vendorPart, op == 'I')
		if e != nil {
			r.Error = "board"
			return
		}
		defer vendor.Close()
	}
	if op == 'I' {
		if fd < 0 {
			r.Error = "file"
			return
		}
		owned, dupErr := syscall.Dup(fd)
		if dupErr != nil {
			r.Error = "io"
			return
		}
		syscall.CloseOnExec(owned)
		src := os.NewFile(uintptr(owned), "user-selected-file")
		// Own a duplicate so the request's received descriptor always has a single owner.
		defer src.Close()
		st, err := src.Stat()
		if err != nil || !st.Mode().IsRegular() {
			r.Error = "file"
			return
		}
		// Reject writes to a filesystem currently mounted, even if boot arguments were stale.
		mounts, err := os.ReadFile("/proc/self/mountinfo")
		if err != nil {
			r.Error = "board"
			return
		}
		var dev syscall.Stat_t
		if syscall.Fstat(int(vendor.Fd()), &dev) != nil {
			r.Error = "board"
			return
		}
		devnum := fmt.Sprintf("%d:%d", (dev.Rdev>>8)&4095, (dev.Rdev&255)|((dev.Rdev>>12)&0xffffff00))
		for _, line := range strings.Split(string(mounts), "\n") {
			fields := strings.Fields(line)
			if len(fields) > 2 && fields[2] == devnum {
				r.Error = "mounted"
				return
			}
		}
		source, err := profile.FromFile(src, st.Size())
		if err != nil {
			e = err
		} else {
			e = slot.Install(control, vendor, r.Active, source)
		}
	} else if op != 'S' {
		e = slot.Action(control, vendor, r.Active, op)
	}
	if e != nil {
		switch {
		case errors.Is(e, slot.ErrState):
			r.Error = "state"
		case errors.Is(e, slot.ErrSlot):
			r.Error = "integrity"
		case errors.Is(e, profile.ErrFormat), errors.Is(e, profile.ErrMismatch), errors.Is(e, io.EOF):
			r.Error = "file"
		default:
			r.Error = "io"
		}
		return
	}
	r.State, e = slot.Read(control)
	if e != nil {
		r.Error = "io"
		return
	}
	r.OK = true
	return
}
func receive(c *net.UnixConn) {
	defer c.Close()
	if !peerSystem(c) {
		return
	}
	c.SetReadDeadline(time.Now().Add(5 * time.Second))
	var b [1]byte
	anc := make([]byte, syscall.CmsgSpace(4*8))
	n, o, flags, _, err := c.ReadMsgUnix(b[:], anc)
	if err != nil {
		return
	}
	msgs, err := syscall.ParseSocketControlMessage(anc[:o])
	if err != nil {
		return
	}
	var fds []int
	for _, m := range msgs {
		if m.Header.Level == syscall.SOL_SOCKET && m.Header.Type == syscall.SCM_RIGHTS {
			v, err := syscall.ParseUnixRights(&m)
			if err != nil {
				return
			}
			fds = append(fds, v...)
		}
	}
	defer func() {
		for _, fd := range fds {
			syscall.Close(fd)
		}
	}()
	if n != 1 || flags&syscall.MSG_CTRUNC != 0 || b[0] == 'A' || (b[0] == 'I' && len(fds) != 1) || (b[0] != 'I' && len(fds) != 0) {
		return
	}
	var in int = -1
	if len(fds) == 1 {
		in = fds[0]
	}
	// The incoming descriptors remain owned by receive; duplicate only after the board is validated.
	r := operate(b[0], in)
	c.SetWriteDeadline(time.Now().Add(5 * time.Second))
	json.NewEncoder(c).Encode(r)
}
func main() {
	debug.SetMemoryLimit(90 << 20)
	if len(os.Args) == 2 && os.Args[1] == "complete" {
		if active() == "kept" {
			r := operate('A', -1)
			if !r.OK {
				fmt.Fprintln(os.Stderr, "GPU confirmation:", r.Error)
				os.Exit(1)
			}
		}
		return
	}
	num, e := strconv.Atoi(os.Getenv("ANDROID_SOCKET_pixel2_gpu"))
	if e != nil || num < 3 {
		os.Exit(2)
	}
	// Android init creates and binds the socket; the service starts listening.
	if e = syscall.Listen(num, 4); e != nil {
		panic(e)
	}
	f := os.NewFile(uintptr(num), "pixel2_gpu")
	l, e := net.FileListener(f)
	f.Close()
	if e != nil {
		panic(e)
	}
	u := l.(*net.UnixListener)
	for {
		c, e := u.AcceptUnix()
		if e != nil {
			panic(e)
		}
		receive(c)
	}
}
