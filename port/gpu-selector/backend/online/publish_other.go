//go:build !windows

// SPDX-License-Identifier: Apache-2.0
package online

import "os"

func publish(from, to string) error { return os.Link(from, to) }
