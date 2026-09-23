# Parallel processing Application

## 簡介

平行處理應用程式是將執行模組服務以容器封裝的服務應用程式，其封裝後的介面繼承 [Algorithm service Application](https://github.com/eastmoon/algorithm-service-application) 專案，但在執行結構改用以下邏輯：

![](doc/img/parallel-processing-concept.svg)

+ [API ( Application Interface )](./doc/01.api-design-specification.md)：網際網路應用程式介面，主要提供給遠端主機透過網路調用服務，例如 ```curl http://[host-name]/api/exec```
+ [CLI ( Command-Line Interface )](./doc/01.cli-design-specification.md)：命令列 ( 控制台 ) 介面，主要提供給本地主機透過命令調用服務，例如 ```ppa exec```
+ [WM ( WorkManager )](./doc/01.wm-design-specification.md)：工作管理者，主要提供平行處理的協調服務單元，其應包括以下功能
  - [Inter-process communication](./doc/02.ipc-technology-specification.md) with Socket：工作訊息接收機制
  - Message queue：工作訊息柱列機制
  - Workers coordination：工作指派機制
  - Workers managenent：工作者數量管理機制

##
