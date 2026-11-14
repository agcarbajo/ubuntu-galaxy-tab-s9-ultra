# Experiment only, never shipped.  Build against the tree the running kernel
# came from and sign with that tree's key, or lockdown refuses the module:
#
#   make -C $KERNEL_BUILD_DIR M=$PWD ARCH=arm64 LLVM=1 modules
#   $KERNEL_BUILD_DIR/scripts/sign-file sha512 \
#       $KERNEL_BUILD_DIR/certs/signing_key.pem \
#       $KERNEL_BUILD_DIR/certs/signing_key.x509 gts9u_ice_rate.ko
#
# On the tablet: insmod gts9u_ice_rate.ko rate=201500000; rmmod gts9u_ice_rate
# The rate stays until the next boot.
obj-m := gts9u_ice_rate.o
