---
name: youbeiwuhuan
description: 北邮校园小管家，把课表、未交作业和校园通知自动同步到同学的电脑与手机。当用户要安装部署邮备无患、开箱即用校园助手、或询问北邮日程作业课表通知时使用，仅限北邮场景。
---

# 邮备无患 · 部署与使用

用户零基础。所有命令你来执行，用户只做两件事：**报一次学号密码**、**在网页点一次登录**。不要解释原理，做就行，做完用大白话告诉用户下一步。

## 一、首次部署（Windows）

1. 确保 Node.js 存在，否则执行：
   `winget install -e --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements`
2. 运行部署脚本（国内镜像加速，幂等，失败可重跑）：
   `powershell -ExecutionPolicy Bypass -File scripts/install.ps1`
   脚本会询问学号和教务密码——让用户自己输入，你绝不能报出、记录或写入回复。
   脚本还会自动把本技能装进 DeepSeek Harness 的技能目录（`~/.dsh/skills/youbeiwuhuan/`）并拉起本地服务，不要你手动复制。
   （技能根目录另有一键安装.bat，供用户不用 WorkBuddy 时自己双击。）
3. 结束后浏览器会打开 http://127.0.0.1:3080 ：
   - 让用户登录他的账号、填一个模型 API Key（一句提示即可，不要替他输密钥）。
   - 再按 assets/手机端说明.txt 把手机连上（装 App → 登录 → 选这台电脑）。
4. 自检：运行 `python scripts/fetch_undone.py`，确认能返回 JSON 且不含密码字段。

## 二、日常问答

四个能力都「结论先行、说人话」，没有就说没有，绝不编。

### 作业
- 问「还有什么作业没交」→ 执行 `python scripts/fetch_undone.py`，未交作业按截止时间从近到远列；<24 小时的标红提醒。

### 日程（写 / 查 / 删）
- 查：问「今天有什么日程 / 我的日程 / 明天有什么安排」→ 执行 `python scripts/schedule.py today`（只看今天）或 `python scripts/schedule.py list`（全部），按时间顺序念出来。
- 写：说「帮我记个日程 / 提醒我 XX」→ 先把时间换算成 `YYYY-MM-DD HH:MM`（没写时刻就 `YYYY-MM-DD`），再执行 `python scripts/schedule.py add "事项" "时间" "备注"`（备注可省）。今天/明天/后天要换算成真实日期，上午/下午/晚上换算成 24 小时制。
- 完成：说「XX 做完了」→ 先 `python scripts/schedule.py list` 找到对应 id，再 `python scripts/schedule.py done <id>`。
- 删除：说「删掉 XX 日程」→ 先 list 找 id，再 `python scripts/schedule.py del <id>`。

### 课表
- 问「今天有什么课 / 今天的课」→ 执行 `python scripts/courses.py`，按节次顺序念课名、时间、教室、老师。
- 问「这周有什么课 / 整周课表 / 明天什么课 / 周几的课」→ 执行 `python scripts/courses.py --week`，按周一~周日分组念，哪天没课就说「这天没课」。

### 通知
- 问「学校有什么新通知 / 有什么重要通知」→ 执行 `python scripts/notices.py`（会短暂弹一下浏览器窗口，属正常），按日期从新到旧挑重点念：与学生相关的、竞赛/报名/讲座/志愿的优先；科研外协公示、预算这类噪音跳过。

- 只说大白话：禁止出现 token / API / 端口 / 脚本 / JSON 等词。

## 三、红线

- 学号密码只写本机 config.json；不打印、不进聊天记录、不进 git。
- 抓作业、抓通知时会短暂弹出浏览器窗口（学校登录页加了反爬，需真实浏览器绕过），这是正常的，别关它，结束会自动关闭。
- 登录失败就如实说「学校系统这会儿登不上，稍后再试」，不要反复重试轰炸。
- 不要改用户其它软件配置；只操作本技能目录和 Node.js 安装。