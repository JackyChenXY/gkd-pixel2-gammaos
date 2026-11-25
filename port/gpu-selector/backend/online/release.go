// SPDX-License-Identifier: Apache-2.0
package online

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"time"
)

const firmwareURL = "https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/download/v0.3.0/GKD-Pixel2-GammaOS.img.gz"

func OpenFirmware(ctx context.Context, size int64) (io.ReadCloser, error) {
	c := webClient()
	c.Timeout = 45 * time.Minute
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, firmwareURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "GKD-Pixel2-Setup/0.3.0")
	req.Header.Set("Accept-Encoding", "identity")
	resp, err := c.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK || (resp.ContentLength >= 0 && resp.ContentLength != size) {
		resp.Body.Close()
		return nil, fmt.Errorf("公开镜像下载失败（HTTP %d，%d 字节）", resp.StatusCode, resp.ContentLength)
	}
	return resp.Body, nil
}

// PublishNew commits a completed file without replacing an existing destination.
func PublishNew(temp, dest string) error { return publish(temp, dest) }
