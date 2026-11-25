// SPDX-License-Identifier: Apache-2.0
package online

import "syscall"

// Both paths are in one directory. MoveFileW never replaces an existing destination,
// including on FAT/exFAT where a hard link is unavailable.
func publish(from, to string) error {
	a, err := syscall.UTF16PtrFromString(from)
	if err != nil {
		return err
	}
	b, err := syscall.UTF16PtrFromString(to)
	if err != nil {
		return err
	}
	return syscall.MoveFile(a, b)
}
