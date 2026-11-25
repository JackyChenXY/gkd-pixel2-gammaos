#!/system/bin/sh
# Expose the extra library only on the device and vendor layout it was built for.
# Every original name under /odm/lib must still resolve to the original target.
set -eu
[ "$(getprop ro.product.vendor.device)" = gkd_pixel2 ]
[ "$(getprop ro.gsid.image_running)" = 0 ]
[ "$(ls -A /odm/lib)" = modules ]
[ -L /odm/lib/modules ] && [ "$(readlink /odm/lib/modules)" = /odm_dlkm/lib/modules ]
read hash name <<EOF
$(sha256sum /vendor/lib/libgallium_dri.so)
EOF
[ "$hash" = 8f225f82a0fd10912e7e8ad6d678d51da076ad4b96cbf863b3b861fc28ba3801 ]
setprop sys.pixel2.krkr_layout valid
