//go:build !windows

// SPDX-License-Identifier: Apache-2.0
package main

import (
	"fmt"
	"os"
)

func launchImager(list string) error { fmt.Println("Imager manifest:", list); return nil }
func displayError(message string)    { fmt.Fprintln(os.Stderr, message) }
