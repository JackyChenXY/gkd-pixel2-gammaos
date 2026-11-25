// SPDX-License-Identifier: Apache-2.0
package online

import (
	"context"
	"fmt"
	"io"
	"os"
)

const LauncherName = "AT4K-H700.apk"

var launcher = asset{
	label: "AT4K 1.2 桌面和 H700 壁纸", size: 12272145,
	digest: "b2fa0343e903ad01c3854999dba70335ba4df5f5522dd931ed9d7189cf841a7d",
	urls: []string{
		"https://raw.githubusercontent.com/LPF970915/H700Android/a8f95e13a91b7f8bd40f2fcb2bc246e3d1c13dc5/android/h700-android10/device/roc/rgsp/prebuilt/AT4K/AT4K.apk",
		"https://api.github.com/repos/LPF970915/H700Android/git/blobs/93cd7b2b8a36b2f12f76f48359527d17a2a63b23",
	},
}

func Desktop(ctx context.Context, local string, say func(string)) ([]byte, error) {
	if local == "" {
		return fetch(ctx, webClient(), launcher, say)
	}
	f, err := os.Open(local)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, launcher.size+1))
	if err != nil {
		return nil, err
	}
	if !matches(data, launcher.size, launcher.digest) {
		return nil, fmt.Errorf("本地 AT4K 与指定版本不符：%s", local)
	}
	return data, nil
}
