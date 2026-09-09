#!/usr/bin/env python3
"""Validate the release NPU package contents without loading hardware modules."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

package = Path(sys.argv[1])
data = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", str(package)])
with tarfile.open(fileobj=io.BytesIO(data)) as archive:
    names = {m.name.removeprefix("./") for m in archive.getmembers()}
    assert not any("/models/" in n or n.endswith((".gguf", ".onnx", ".desktop")) for n in names)
    assert not any("gts9u-ai" in n or "gts9u-npu-app" in n or "gts9u-npu-llama" in n or "gts9u-npu-whisper" in n for n in names)
    assert not any("multi-user.target.wants" in n for n in names)
    assert "usr/lib/firmware/qcom/sm8550/cdspr.jsn" not in names  # hardware package owns this map
    for name in ("gts9u_cdsp", "gts9u_dsp_stats", "system_heap", "gts9u_fastrpc_prepared", "gts9u_cdsp_intents_probe"):
        assert "opt/gts9u-npu-session/modules/" + name + ".ko" in names
    for name in ("opt/gts9u-npu/bin/cdsprpcd", "opt/gts9u-npu-bionic/bin/linker64", "opt/gts9u-npu-bionic/bin/probe-npu-htp", "etc/systemd/system/gts9u-npu.service"):
        assert name in names, name
    evidence = json.load(archive.extractfile("./usr/share/doc/ubuntu-gts9u-npu/inputs.json"))
    assert evidence["module_signing_certificate_serial"]
print("PASS: NPU support and signed modules present; no AI app, models or boot activation")
