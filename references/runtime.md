# 运行文件与可移植性

本版默认业务流程使用18目标候选数据层，同时保留独立的12项目、16来源版本。所有脚本从自身位置定位资源，不依赖开发机盘符或父仓库Python模块；移动Skill根目录时保持内部结构。

## 完整运行资料

```text
kcsz-course-survey/
  SKILL.md
  scripts/
    candidate_data.py
    import_candidate_handoff.py
    candidate_survey.py
    chaoxing_export.py
    teachclaw_entry.py
    survey_data.py
    survey_presentation.py
    survey_export.py
  data/
    candidates/                 交接CSV、清单、三维配置与映射说明原文
    catalog.json
    presentation-rules.json
    questionnaires/             全部16来源JSON
  assets/
    importQuestionTemplateNew.xls
    chaoxing-template-profile.json
  docs/
    武汉大学课程思政教学评价指南（第一辑）.pdf
    武汉大学课程思政教学评价指南（第二辑）.pdf
  references/
```

发布ZIP包括上述新旧资源及白名单测试/说明。[BUILDING.md](../BUILDING.md)列出构建边界。`survey_delivery.py`为旧16来源版本的集中交付工具，不用作新版候选抽题入口。

候选数据每次加载核对本地导入清单、原始交接哈希、505条来源的30字段、候选与来源双向引用、教师事件、各项目数量及主维度证据。学习通模板与配置独立核验哈希。运行中不执行原交接包脚本，也不需要回到原ZIP下载目录。

旧 `SurveyStore.validate_all()`读取两份PDF的原始字节并校验SHA-256。旧目录的list/find/read/export均先全库校验；缺失或改动会失败。运行不解析PDF，不需要PDF库，不能通过删除资料或忽略错误伪装成可移植。候选流程不依赖旧PDF的展示规则，但完整包仍携带旧接口所需资料。

## 环境与输出

生产核心需要Python3.10+、对Skill的读权限及对输出目录的写权限，只用标准库，不安装第三方包。当前主开发检查使用3.14.7；旧来源版另有3.12.14记录，最低3.10未单独实测。运行不需要模型或问卷星Key、Gateway/OpenClaw服务或网络；自然语言理解由宿主管理。

候选默认写入 `output/candidates/` 独立目录，主文件 `questionnaire.txt` 或 `questionnaire.xls`，另附教师说明与manifest。旧来源版仍使用 `survey.pending-import.txt`。安装位置只读时用 `--output-dir` 指向可写位置，不更改宿主权限；结果路径以 `artifacts[].path` 为准。

每次输出保存实际选题、请求数量、种子、各目标分配、候选ID、来源原始字段及五类独立批准。学生题面不展示项目/维度、风险和候选库标签。XLS为二进制文件，宿主不可把它按UTF-8文本解码后再写回。

## 移位后的检查

从与Skill无关的cwd，使用脚本的绝对路径执行：

```powershell
python -B <skill-root>/scripts/candidate_data.py validate
python -B <skill-root>/scripts/survey_data.py validate
python -B <skill-root>/scripts/candidate_survey.py --goal creativity --question-count 8 --format wjx
python -B <skill-root>/scripts/candidate_survey.py --goal patriotic-attitude --goal creativity --goal learning-self-efficacy --question-count 10 --format chaoxing
```

上述 `<skill-root>` 表示已确认的实际路径，不是宿主自动替换协议。核对三份产物存在、题数、核心/备份范围、选题ID、来源映射及主文件哈希，再在实际宿主验证加载、参数和文件交付。

TeachClaw通过monorepo统一Windows Runner与宿主插件接入；本Skill ZIP不安装该插件，不更改QQ账号或私密允许名单。固定命令与旧来源兼容见 [TeachClaw说明](teach-claw.md)，本地核心测试不能代替当次跨环境执行或QQ实际收件。

问卷星和学习通实际导入另行核对；旧反馈见 [import-feedback.md](import-feedback.md)。软件发布不授予候选题施测资格；来源与许可范围见 [SOURCES.md](../SOURCES.md)。
