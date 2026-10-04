# 第三方授權聲明與盤點

盤點日期：2026-10-04。範圍：公開版 Service Harbor 的 Git 追蹤檔案、前端引用及目前安裝環境中的 Python 執行期套件授權 metadata。

## 授權範圍

根目錄 LICENSE 僅適用於本專案著作權人有權授權的原創內容。第三方內容仍適用其原始授權與署名；以下授權原文逐位元組保留，不以 xthywork 取代原作者。

## Python 執行期依賴

requirements.txt 直接依賴 FastAPI 與 Uvicorn，其餘為目前環境的間接依賴。套件程式碼與虛擬環境未隨本 repository 散布，由安裝器另行安裝。下表是實際安裝版本的授權快照，不是版本鎖定；未來安裝結果可能不同，更新或重新散布時應重新核對實際版本及其內含聲明。

| 套件 | 盤點版本 | 套件宣告授權 | 保留原文 |
| --- | --- | --- | --- |
| fastapi | 0.141.1 | MIT | [原始聲明](licenses/third-party/fastapi.txt) |
| uvicorn | 0.53.0 | BSD-3-Clause | [原始聲明](licenses/third-party/uvicorn.txt) |
| starlette | 1.6.0 | BSD-3-Clause | [原始聲明](licenses/third-party/starlette.txt) |
| pydantic | 2.13.5 | MIT | [原始聲明](licenses/third-party/pydantic.txt) |
| pydantic_core | 2.46.5 | MIT | [原始聲明](licenses/third-party/pydantic_core.txt) |
| anyio | 4.15.1 | MIT | [原始聲明](licenses/third-party/anyio.txt) |
| h11 | 0.16.0 | MIT | [原始聲明](licenses/third-party/h11.txt) |
| click | 8.5.0 | BSD-3-Clause | [原始聲明](licenses/third-party/click.txt) |
| idna | 3.20 | BSD-3-Clause | [原始聲明](licenses/third-party/idna.txt) |
| typing_extensions | 4.16.0 | PSF-2.0 | [原始聲明](licenses/third-party/typing_extensions.txt) |
| typing-inspection | 0.4.4 | MIT | [原始聲明](licenses/third-party/typing-inspection.txt) |
| annotated-types | 0.8.0 | MIT | [原始聲明](licenses/third-party/annotated-types.txt) |
| annotated-doc | 0.0.5 | MIT | [原始聲明](licenses/third-party/annotated-doc.txt) |

以上原文來自各套件 wheel 的 `.dist-info/licenses/`。散布套件、二進位或完整環境時，應保留該版本全部授權與通知；BSD 條款另包含二進位散布的通知要求及不得藉原作者名義背書的限制。這份套件層級盤點不是原生二進位內所有間接元件的完整 SBOM。

## 前端程式、圖示與字型

- HTML 僅引用 repository 內的 JavaScript 與 CSS；未發現第三方前端框架或 CDN 資源。
- 圖示使用文字符號及 tracking.js 的內嵌 SVG；未發現隨附圖示套件、圖片素材或既有第三方署名。僅憑原始碼無法獨立證明每一段程式或 SVG 的創作來源；未來若確認有第三方來源，須補上其授權及署名。
- CSS 指定 DM Sans、Inter、DM Mono 等字型名稱及系統 fallback，未隨附字型檔，也未使用 @font-face 或遠端字型下載。使用者電腦的字型依原有授權，不受本專案 MIT 授權影響。未來若隨附字型，須另外核對並保留字型授權。

## 外部工具

Python、pip、uv、systemd、OpenSSH 及 Ubuntu 系統工具未隨本 repository 散布。安裝說明包含 uv 官方安裝器連結，但不包含安裝器或 uv 的程式碼。這些工具仍依各自授權；若製作包含工具的容器或安裝映像，須另行盤點完整內容，不能僅附本專案 LICENSE。

## 參考

- [MIT 標準條文（Open Source Initiative）](https://opensource.org/license/mit)
- [FastAPI 原始授權](https://github.com/fastapi/fastapi/blob/master/LICENSE)
- [Uvicorn 原始授權](https://github.com/encode/uvicorn/blob/master/LICENSE.md)
- [AnyIO 原始授權](https://github.com/agronholm/anyio/blob/master/LICENSE)

上游連結可能隨版本變動；本目錄保留的原文對應上表的盤點版本。
