//go:build windows

// SPDX-License-Identifier: Apache-2.0
package main

import (
	_ "embed"
	"encoding/base64"
	"encoding/binary"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"pixel2/gpu/card"
	"syscall"
	"unicode/utf16"
	"unsafe"
)

//go:embed imager.ps1
var launcher string

func systemDirectory() (string, error) {
	var buf [32768]uint16
	n, _, err := syscall.NewLazyDLL("kernel32.dll").NewProc("GetSystemDirectoryW").Call(uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)))
	if n == 0 || n >= uintptr(len(buf)) {
		return "", err
	}
	return syscall.UTF16ToString(buf[:n]), nil
}
func launchImager(list string) error {
	dir, err := systemDirectory()
	if err != nil {
		return err
	}
	units := utf16.Encode([]rune(launcher))
	data := make([]byte, len(units)*2)
	for i, u := range units {
		binary.LittleEndian.PutUint16(data[i*2:], u)
	}
	cmd := exec.Command(filepath.Join(dir, "WindowsPowerShell", "v1.0", "powershell.exe"), "-NoProfile", "-NonInteractive", "-EncodedCommand", base64.StdEncoding.EncodeToString(data))
	cmd.Env = append(os.Environ(), "PIXEL2_LOCAL_MANIFEST="+list)
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err = cmd.Run(); err != nil {
		return fmt.Errorf("刷卡器启动未完成。可在 Imager 中选择已生成的 %s，或重新运行安装助手。%w", card.PersonalName, err)
	}
	return nil
}
func displayError(message string) {
	dir, err := systemDirectory()
	if err != nil {
		return
	}
	msg, _ := syscall.UTF16PtrFromString(message)
	cap, _ := syscall.UTF16PtrFromString(title)
	syscall.NewLazyDLL(filepath.Join(dir, "user32.dll")).NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(msg)), uintptr(unsafe.Pointer(cap)), 0x10)
}
