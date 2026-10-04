# 运行文件与可移植性

查询、呈现、导出核心可独立于父仓库调用，但必须按相对目录整体携带运行资料。缺少原PDF会导致来源完整性校验失败，不能通过忽略错误伪装成可移植。

## 必须携带

```text
kcsz-course-survey/
  SKILL.md
  references/                 本Skill链接的调用、反馈及宿主说明
  scripts/
    survey_data.py
    survey_presentation.py
    survey_export.py
  data/
    catalog.json
    presentation-rules.json
    questionnaires/           全部16份来源JSON，原名与索引一致
  docs/
    武汉大学课程思政教学评价指南（第一辑）.pdf
    武汉大学课程思政教学评价指南（第二辑）.pdf
```

Python核心最少23个文件：3个模块、18个数据JSON、2个原PDF；宿主Skill加载还需SKILL.md及其引用说明。`scripts/survey_delivery.py`仅为全部16版集中交付工具，若要使用它也必须携带，仍只依赖标准库和上述核心。

PDF是运行完整性校验依赖：`SurveyStore.validate_all()`读取原文件字节并校验SHA-256，list/find/read/export均先执行全库校验。本程序不在运行中解析PDF，不需要pypdf、pdfplumber或Poppler。PDF必须以实际原文件名位于根目录下docs，不能重命名、删掉或修改。缺失时报`INVALID_DATA/SOURCE_MISSING`，哈希不一致时报`SOURCE_HASH_MISMATCH`。

审计报告、测试、旧output、tmp均不参与核心运行。公开源码附带测试与构建说明供开发使用，白名单构建范围见[BUILDING.md](../BUILDING.md)；审计报告、历史产物和临时资料不进入发布候选。不要把历史导出、临时提取文件或整套开发仓库作为Skill的运行依赖，不绕过原PDF校验。

## 环境与输出

需要已有Python 3.10+及对Skill文件的读权限、对输出目录的写权限。最低版本依据当前类型语法及`Path.write_text(newline=...)`接口；此前本地验证实际使用Python 3.14.7、3.12.14，未实测最低版本3.10。运行不需要第三方Python包、模型或问卷星Key、Gateway/OpenClaw服务或网络调用。宿主理解自然语言所用模型由宿主管理。

脚本从自身位置定位资源；无硬编码F盘路径、用户主目录或父仓库模块导入。移动根目录时保持内部结构，重新定位脚本即可。输出默认根目录/output；只读安装位置可通过用户提供的可写`--output-dir`覆盖，错误时不修改宿主权限。输出实际路径由artifacts返回，不推测目录名。

Python核心的默认文件名仍为`survey.pending-import.txt`，每次位于唯一问卷目录；宿主应按artifacts返回该实际文件，可使用宿主真实附件名称展示能力，但不能重新生成或改写题面。

## 迁移后的最短检查

先用实际解释器执行`survey_data.py validate`，确认12项目/16版本全库通过，再从另一个cwd调用`survey_export.py --project creativity`（不指定输出或版本），核对产物位于迁移后根目录/output、版本为original、三个实际文件存在。带中文路径时也做同样检查。

然后在目标宿主实际加载SKILL.md，用自然语言口令验证模型理解与调度。此前包的WorkBuddy加载和创造力生成已有用户成功反馈；新候选的本地检查不等于重新宿主运行。teach_claw留到后续版本。问卷星导入反馈的2/14状态另见[import-feedback.md](import-feedback.md)，来源与再分发许可见[SOURCES.md](../SOURCES.md)。
