/* SPDX-License-Identifier: Apache-2.0 */
#ifndef PIXEL2_GROW_CARD_H
#define PIXEL2_GROW_CARD_H
#include <stdint.h>
int pixel2_grow_fd(int fd, uint64_t bytes, uint64_t image_bytes, const unsigned char guid[16],
                   uint32_t original_crc, uint64_t *userdata_start);
int pixel2_grow_sd(unsigned unit, uint64_t image_bytes, const unsigned char guid[16], uint32_t table_crc);
#endif
