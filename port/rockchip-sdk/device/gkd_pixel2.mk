PRODUCT_SHIPPING_API_LEVEL := 31
PRODUCT_DTBO_TEMPLATE := device/gamekiddy/gkd_pixel2/dt-overlay.in

include device/rockchip/common/build/rockchip/DynamicPartitions.mk
include device/gamekiddy/gkd_pixel2/BoardConfig.mk
include device/rockchip/common/BoardConfig.mk

$(call inherit-product, device/rockchip/rk3326/device-common.mk)
$(call inherit-product, device/rockchip/common/device.mk)

PRODUCT_CHARACTERISTICS := tablet

PRODUCT_NAME := gkd_pixel2
PRODUCT_DEVICE := gkd_pixel2
PRODUCT_BRAND := GameKiddy
PRODUCT_MODEL := GKD Pixel 2
PRODUCT_MANUFACTURER := GameKiddy
PRODUCT_AAPT_PREF_CONFIG := mdpi

DEVICE_PACKAGE_OVERLAYS += device/gamekiddy/gkd_pixel2/overlay

PRODUCT_PROPERTY_OVERRIDES += ro.sf.lcd_density=160

PRODUCT_COPY_FILES += \
    device/gamekiddy/gkd_pixel2/keylayout/gkd_pixel2_joypad.kl:system/usr/keylayout/gkd_pixel2_joypad.kl
