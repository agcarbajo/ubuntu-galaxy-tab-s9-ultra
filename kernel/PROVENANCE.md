# Procedencia de las fuentes de kernel importadas

Todo lo que hay bajo `kernel/` procede del port postmarketOS del mismo
dispositivo y conserva su licencia y autoría:

- Repositorio de origen:
  <https://github.com/agcarbajo/postmarketos-galaxy-tab-s9-ultra>
- Commit de referencia del relevo: `b1dcca0`
- Paquete de origen:
  `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/`
- Baseline: postmarketOS v1.71, kernel package r114
- Kernel base: Linux mainline 7.2-rc3, commit
  `a13c140cc289c0b7b3770bce5b3ad42ab35074aa`

Licencias, sin excepción:

| Ruta | Licencia | Motivo |
|---|---|---|
| `kernel/drivers/*.c` | `GPL-2.0-only` | Obras derivadas de Linux |
| `kernel/patches/*.patch` | `GPL-2.0-only` | Obras derivadas de Linux |
| `kernel/dts/*.dts` | `BSD-3-Clause` | Convención de los DTS Qualcomm upstream |
| `kernel/config/*` | `MIT` | Configuración del proyecto |

La cabecera SPDX de cada fichero prevalece sobre el MIT por defecto del
repositorio.

## Inventario

Se completa a medida que se importa cada fichero, con el hash SHA-256 de la
copia de origen para poder detectar divergencias futuras.

| Fichero | Origen en el port pmOS | SHA-256 de origen |
|---|---|---|
| `configs/dtbo/gts9uwifi-board00-noop.dts` | `configs/dtbo/gts9uwifi-board00-noop.dts` | `d205430481e46caa67932a77b3a4712f3b8ead5a96ef688190fbffca2a159e0f` |
| `configs/dtbo/gts9uwifi-board03-noop.dts` | `configs/dtbo/gts9uwifi-board03-noop.dts` | `fe4cc70edb5e2c92b3c34bfbfca3d15c2ad386feaa6ddc109ebbe632acbd9145` |
| `configs/vendor_boot/bootconfig.txt` | `configs/vendor_boot/bootconfig.txt` | `f85fa97b8a180cac5e1bc583585e774042df5b5a756119d6b31cacd3504c16e0` |
| `configs/vendor_boot/cmdline.txt` | `configs/vendor_boot/cmdline.txt` | `847006d1438a43e1e848f6ab42e1f7cabbf85b7c7b955d2c7f2bd5ceac48c793` |
| `kernel/config/config-gts9uwifi.fragment` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/config-gts9uwifi.fragment` | `c6b57032a2171dec1c847385adee5d4263769c3578acba629c0fa023285f9b8f` |
| `kernel/config/config-mainline.aarch64` | `/root/pmos-gts9u/pmaports/device/main/linux-postmarketos-mainline/config-mainline.aarch64` | `661c45023794690f38609be08e5a2a0b77eef5224f48f971f6d709a1871d132b` |
| `kernel/drivers/panel-samsung-ana38407.c` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/panel-samsung-ana38407.c` | `354a5dad9aa119475971d6b7bb347293c2afaff1384f9c79c589f065cddeae24` |
| `kernel/drivers/ps5169.c` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/ps5169.c` | `9002b6a8b6794749dedb42e2530f040995916638f2af51d4fa9f898dfc997b74` |
| `kernel/drivers/sm5440_direct.c` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/sm5440_direct.c` | `fd6ce815cfa8718d2ad0d01ea3cc712d93e73b7b2acb2a1ac18e6b7537852a34` |
| `kernel/drivers/sm5714_battery.c` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/sm5714_battery.c` | `91e5766a09c91df4cdfb0f7ffbe297e68ab8e2b8c0392d777995fc56e50a656f` |
| `kernel/drivers/sm5714_usbpd.c` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/sm5714_usbpd.c` | `f51803065b130427c1f733be595bd3230eca02c69f723c6a490774d6f7dd3a92` |
| `kernel/drivers/samsung_stm32_pogo.c` | Adaptación mainline del protocolo de `kernel/vendor/samsung-stm32-pogo/` | Véase `kernel/vendor/samsung-stm32-pogo/SHA256SUMS` |
| `kernel/dts/sm8550-samsung-gts9uwifi.dts` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/sm8550-samsung-gts9uwifi.dts` | `a9ff4284183c7943b2a94ac704e19b3974a58197f082e2602e1aea09f7851937` |
| `kernel/patches/add-gts9uwifi-dtb.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/add-gts9uwifi-dtb.patch` | `36acdf4aff5abb1022edb431b39b0f99e680b9a006c859ed1f986fea7f788da3` |
| `kernel/patches/add-samsung-sec-log-console.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/add-samsung-sec-log-console.patch` | `8a0d84ca1a2e32c937edca91752379429e42563a3308f1b880381191e6b3bfba` |
| `kernel/patches/build-wcn-pcie-providers-in.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/build-wcn-pcie-providers-in.patch` | `279b162777a99f533eb09377270003ceef82c692e6de7faecbb47580182e5678` |
| `kernel/patches/configure-nxp-ptn3222-from-dt.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/configure-nxp-ptn3222-from-dt.patch` | `80332e96ee5b468b1183e239ff1e8cdf663a688808e6d13b66047767adbbc0b7` |
| `kernel/patches/expose-separate-gpu-kms-resources.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/expose-separate-gpu-kms-resources.patch` | `9578cd1687a11d9780a617cb4335a2780b16ccb1d0835856d9e85e40213d872d` |
| `kernel/patches/ignore-console-null.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/ignore-console-null.patch` | `70b4930e1bdcd99769e59de783ddafafbfe5ec377e3d6c166ef9c63197906123` |
| `kernel/patches/keep-sec-log-previous-index-current.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/keep-sec-log-previous-index-current.patch` | `11b21da7037440b0726c40becd7c5165fe00fcd69bf0165904a3b9b6a61512cd` |
| `kernel/patches/match-samsung-sm8550-eusb2-phy-init.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/match-samsung-sm8550-eusb2-phy-init.patch` | `187d3d425c06ce1c1a204e5655457e39c9771457ad6cb2279243aec49a295990` |
| `kernel/patches/msm-dp-allow-unresolved-usbc-bridge.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/msm-dp-allow-unresolved-usbc-bridge.patch` | `3a1561c3377e7ad825d2f1e147e6ab3a24376f366a9610061c2c7cc3fd9d591c` |
| `kernel/patches/msm-dp-associate-bridge-of-node.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/msm-dp-associate-bridge-of-node.patch` | `998f27d4ae3d44c175268150850e62a33e87c4a87bb57e175e93eae69289a746` |
| `kernel/patches/msm-dp-defer-oob-hpd-until-resume.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/msm-dp-defer-oob-hpd-until-resume.patch` | `5ef69616b98a761353eb89fa7b386b6a761b452c0e30eca9417d9844ab8a7d47` |
| `kernel/patches/qcom-q6v5-mask-completed-handover-irq.patch` | Corrección propia sobre Linux 7.2-rc3 para la IRQ one-shot de handover del ADSP | `a221e088bc4c33f7ff86dfeaa155f46c4f1d947638e2b96729299f6882626598` |
| `kernel/patches/set-mi2s-codec-dai-format.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/set-mi2s-codec-dai-format.patch` | `442ea71ece9b3574f409bb620810e811716404456682c5e6b77edb9dd2c4647b` |
| `kernel/patches/support-samsung-goodix-16-byte-events.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/support-samsung-goodix-16-byte-events.patch` | `0ce2f9466eae22c427b03c5af6a6c7a07fb3530d378581d946d262909d574f3e` |
| `kernel/patches/tcpm-adopt-retained-source-ufp-role.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/tcpm-adopt-retained-source-ufp-role.patch` | `eef7cd7b96373ee8a02ec0d8be91f4e3715a2594a44eb4963ea504dc5199a5b2` |
| `kernel/patches/tcpm-use-retained-sink-data-role.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/tcpm-use-retained-sink-data-role.patch` | `2565ee41257290bd4828fd80a8beda377f284fb2154aab66e47a53a3ebe178c5` |
| `kernel/patches/unpark-pcie0-pipe-mux.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/unpark-pcie0-pipe-mux.patch` | `b435e5297a34ce353eb8e4793546d35c21e120e7ee04b547b73ec1d72dc2dc9b` |
| `kernel/patches/upgrade-partial-goodix-samsung-events.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/upgrade-partial-goodix-samsung-events.patch` | `4f4f03061bca74cf72d3745d86509d90e425a32245f0770dbf44eb50da241993` |
| `kernel/patches/wcn7850-pwrseq-cold-reset-aop.patch` | `pmaports/device/testing/linux-samsung-gts9uwifi-mainline/wcn7850-pwrseq-cold-reset-aop.patch` | `d1fcad07f00cd87f4b5bbce7cb32128e23023c34f05e94dbba3da5d85e2816a9` |
