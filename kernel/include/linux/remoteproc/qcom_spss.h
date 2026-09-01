/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Copyright (c) 2021, Qualcomm Innovation Center, Inc. All rights reserved.
 * Copyright (c) 2021, The Linux Foundation. All rights reserved.
 */

#ifndef _QCOM_RPROC_SPSS_H_
#define _QCOM_RPROC_SPSS_H_

struct device;
struct device_node;
struct qcom_glink_spss;
struct rproc;

/*
 * Include this file only after including linux/remoteproc.h
 */

extern int qcom_spss_set_fw_name(struct rproc *rproc, const char *fw_name);
struct qcom_glink_spss *qcom_glink_spss_register(struct device *parent,
						 struct device_node *node);
void qcom_glink_spss_unregister(struct qcom_glink_spss *spss);

#endif
