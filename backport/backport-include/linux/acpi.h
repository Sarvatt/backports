#ifndef __BACKPORT_LINUX_ACPI_H
#define __BACKPORT_LINUX_ACPI_H
#include_next <linux/acpi.h>
#include <linux/version.h>

#if LINUX_VERSION_CODE < KERNEL_VERSION(3,9,0)
#define ACPI_HANDLE(dev)        DEVICE_ACPI_HANDLE(dev)
#endif

#endif /*  __BACKPORT_LINUX_ACPI_H */
