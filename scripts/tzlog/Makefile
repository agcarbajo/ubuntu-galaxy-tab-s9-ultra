# Out-of-tree build of the TrustZone diagnostic log reader.
#
# This module is a diagnostic and is never installed into the image; build it
# against the same tree and toolchain as the running kernel, or it will not
# load.  Example:
#
#   make -C scripts/tzlog KDIR=/root/ubuntu-gts9u/build/linux-gts9uwifi
#
obj-m += gts9u-tzlog.o
obj-m += gts9u-fpclk.o

KDIR ?= /root/ubuntu-gts9u/build/linux-gts9uwifi
PWD := $(shell pwd)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) ARCH=arm64 LLVM=1 modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) ARCH=arm64 LLVM=1 clean

.PHONY: all clean
