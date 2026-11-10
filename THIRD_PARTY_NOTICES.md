# Third-party notices

Vehicle detection uses the official YOLOX Tiny ONNX COCO model from Megvii-BaseDetection/YOLOX. The project and inference example are licensed under Apache License 2.0. See `licenses/YOLOX-APACHE-2.0.txt` and the upstream repository for notices. The model is downloaded to ignored local storage and is not bundled into the frontend.

The inference preprocessing and grid decoding follow the official YOLOX ONNX Runtime example. The local tracker and application code are provided under the project MIT license.

Traffic imagery and directory data remain subject to each operator's terms. The connected sources are Transport for London, Fintraffic Digitraffic, DriveBC, the City of Calgary, Caltrans, the City of Austin, Statens vegvesen, Vegagerðin, Transpordiamet/Tarktee, Hong Kong Transport Department, Singapore Land Transport Authority, Taiwan Highway Bureau, Transport for NSW, Queensland Transport and Main Roads, NZ Transport Agency Waka Kotahi, and CET São Paulo. Their documentation and attribution statements are listed in `backend/providers.py`, shown in source management, and attached to imported camera images. Custom camera imagery remains attributed to its operator. No imagery is bundled with the project, and public access does not transfer the provider's rights or guarantee worldwide coverage.

Map data is © OpenStreetMap contributors. The Leaflet, React, Next.js, FastAPI, OpenCV, ONNX Runtime, SciPy, and other dependency licenses remain with their respective packages. Starter vendor license files are retained in `dashboard/vendor/`.

Browser HLS playback uses hls.js, Copyright (c) 2017 Dailymotion, licensed under Apache License 2.0 with additional upstream notices in `licenses/HLS-JS-NOTICE.txt`. Live HLS recording uses a system FFmpeg installation; its license depends on the installed build. The Docker image installs Debian's FFmpeg package, including its package license notices.
