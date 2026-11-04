# Sample videos and model: licensing

Video files and model weights are **not committed**. `scripts/fetch_samples.py` downloads them into
`data/samples/` (gitignored) using the manifest below and checks each SHA-256. Attribution appears here
only because the licenses require it.

All clips are used unmodified except for being re-encoded to MP4 without audio and scaled to 640 px wide
for local testing. Re-encoded copies are not redistributed.

<!-- MANIFEST START: camera | zone | license | author | sha256 | url -->
| camera | zone | license | author | sha256 | url |
|---|---|---|---|---|---|
| cam-store | lane-1 | CC BY-SA 4.0 | Awkwafaba | 87540986c80e0c522b64f2630caa15d3289fc67a1ea4e51fab15c07a9fd96629 | https://upload.wikimedia.org/wikipedia/commons/b/b0/Disinfecting_shopping_cart.webm |
| cam-kitchen | kitchen | CC BY-SA 4.0 | Dietmoigianvungtau | d1db95cfae8427c70dcc6b6e6f57aed412554951f1f96bce99a2eecf2b63af5d | https://upload.wikimedia.org/wikipedia/commons/a/a7/Diet_moi_gian_vung_tau_phun_diet_con_trung_nha_hang_maxim_phuong_7.webm |
| cam-lot | fire-lane | CC BY-SA 4.0 | DogeGamer2015MZT2 | 8b9ac75cff08949067df23e0bf0fdb15e1262fe9f93ebfc8c12e15b4b6793501 | https://upload.wikimedia.org/wikipedia/commons/4/4c/Estacionamiento_de_un_Supermercado_Ley%2C_Mazatl%C3%A1n%2C_11_de_junio_de_2022.webm |
| cam-entry | entrance | CC0 1.0 | Taurus Media Technik | bfadaa62cccb42db875d50bb842aa0964fbf72040432e4097c1df59e043e0c26 | https://upload.wikimedia.org/wikipedia/commons/a/ae/Video_Codec_Test_pedestrian_area_1080p25.y4m.webm |
| model | - | Apache-2.0 | Megvii-BaseDetection (YOLOX nano, ONNX export) | c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d | https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx |
<!-- MANIFEST END -->

Source pages: each video's Wikimedia Commons file page (`https://commons.wikimedia.org/wiki/File:<file name>`)
carries its full license text and attribution. CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/ ·
CC0 1.0: https://creativecommons.org/publicdomain/zero/1.0/ · Apache-2.0: https://www.apache.org/licenses/LICENSE-2.0

The clips show public scenes. People in them are not identified; the pipeline never runs face recognition, and
sampled frames are deleted after detection.
