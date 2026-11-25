// SPDX-License-Identifier: Apache-2.0
package online

import (
	"context"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type asset struct {
	label, digest string
	size          int64
	urls          []string
}

func upstream(label, repo, revision, path, blob, digest string, size int64) asset {
	return asset{label: label, size: size, digest: digest, urls: []string{
		"https://raw.githubusercontent.com/TinkerBoard-Android/" + repo + "/" + revision + "/" + path,
		"https://api.github.com/repos/TinkerBoard-Android/" + repo + "/git/blobs/" + blob,
	}}
}

const allocatorPath = "etc/init/android.hardware.graphics.allocator@4.0-service.rc"
const composerPath = "etc/init/android.hardware.graphics.composer@2.1-service.rc"
const driverPath = "lib/egl/libGLES_mali.so"

var allocator = upstream("内存分配配置", "rockchip-android-hardware-libgralloc-bifrost",
	"840796ba9508eab479f2086597cfb8c942e8b1e8", "service/4.x/android.hardware.graphics.allocator@4.0-service.rc",
	"6523f4e71a2b3ddfb07645b69e6305fd94ab8e03", "7975cd3284516cd848027278302998a7b10669aea0d7d078c754255a4709b7f7", 293)
var composer = upstream("显示合成配置", "rockchip-android-hardware-interfaces",
	"9a59bb6a44422046ba17b01ceb2e1b95af0fc074", "graphics/composer/2.1/default/android.hardware.graphics.composer@2.1-service.rc",
	"cbd589afca46b8d38d5ff3a6ba7f1b01bb03453b", "2272ae38541f35caa05f7ca426f690e32b92c930622317e925e7796a29708bfa", 342)
var driver = upstream("Mali-G31 主库", "rockchip-android-vendor-rockchip-common",
	"5aeb28df3d0275ccd579ef99e3c164dabde744e9", "gpu/MaliTDVx/lib/arm/libGLES_mali.so",
	"1bcf5e5eed9dee7bc95f521e3ee43faeb6953324", "3033d08f117dcaf86fa9eab5242b27fdccca7ed252496d7b847c9fb7dd9df07e", 27984132)

//go:embed bundle/support.sha256
var supportDigest string

var support = asset{label: "开源配套文件", digest: strings.TrimSpace(supportDigest), size: 1232951,
	urls: []string{"https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/download/v0.3.0/Pixel2-Mali-Support.zip"}}

func matches(data []byte, size int64, digest string) bool {
	sum := sha256.Sum256(data)
	return int64(len(data)) == size && hex.EncodeToString(sum[:]) == digest
}

func webClient() *http.Client {
	return &http.Client{Timeout: 4 * time.Minute, CheckRedirect: func(next *http.Request, via []*http.Request) error {
		host := next.URL.Hostname()
		github := host == "github.com" || host == "api.github.com" || strings.HasSuffix(host, ".githubusercontent.com")
		if next.URL.Scheme != "https" || !github || len(via) >= 6 {
			return errors.New("下载地址重定向异常")
		}
		return nil
	}}
}

type progress struct {
	total, read int64
	next        int
	say         func(string)
}

func (p *progress) Write(b []byte) (int, error) {
	p.read += int64(len(b))
	percent := int(p.read * 100 / p.total)
	if percent >= p.next {
		p.say(fmt.Sprintf("  %d%%", min(100, percent)))
		p.next = (percent/10 + 1) * 10
	}
	return len(b), nil
}

func get(ctx context.Context, client *http.Client, file asset, url string, say func(string)) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "Pixel2MaliDownload/1.0")
	req.Header.Set("Accept", "application/vnd.github.raw+json")
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	if resp.ContentLength >= 0 && resp.ContentLength != file.size {
		return nil, errors.New("文件长度与固定版本不符")
	}
	var r io.Reader = io.LimitReader(resp.Body, file.size+1)
	if file.size >= 8<<20 {
		r = io.TeeReader(r, &progress{total: file.size, next: 10, say: say})
	}
	data, err := io.ReadAll(r)
	if err != nil {
		return nil, err
	}
	if !matches(data, file.size, file.digest) {
		return nil, errors.New("SHA-256 或文件长度与固定版本不符")
	}
	return data, nil
}

func fetch(ctx context.Context, client *http.Client, file asset, say func(string)) ([]byte, error) {
	say("正在获取" + file.label)
	var last error
	for i, url := range file.urls {
		if i > 0 {
			say("  正在重试 GitHub 的另一个官方入口")
		}
		data, err := get(ctx, client, file, url, say)
		if err == nil {
			return data, nil
		}
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		last = err
	}
	return nil, fmt.Errorf("无法获取%s。请检查网络后重试（%w）", file.label, last)
}
