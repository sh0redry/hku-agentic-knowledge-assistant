# 0.19.2 / Chrome Bridge 0.17.25 修复与最小复验

## 现场验收结论（2026-10-02）

最终 F4 只读演练的本地审计事件为 `dry_run_ready_no_submission`，
完成时间 17:36:12 HKT，`error_code=null`；用户面板报告尝试/成功/写入均为 0。
本次日期、精确空位和账号记录校验通过，未提交真实预约。

授权过期处理会把 runtime.phase 覆盖为 expired，因此当前面板不能直接保留
演练成功阶段；审计事件仍保存原结果。这是下一批待修复的问题，不算真实预约
验收，也不应把“无错误的过期”直接当作成功。

## 隐藏控件补丁：Chrome Bridge 0.17.28

用户控制台诊断确认默认页也保留隐藏搜索面板：`main_ddlSearchStartDate`、
`main_txtSearchStartDate` 有预填默认值，其他隐藏下拉框和备注/邮箱字段存在。
先前代码将这些休眠控件视为筛选，从而继续拒绝空表。

record parser 0.1.6 仅在 Bridge 刚点击唯一的无查询参数/片段默认记录路由时，
接受已知且 `getClientRects().length === 0` 的休眠控件。其他调用不自动获得
这项证明；可见搜索字段、未知字段、非空搜索/事件/当前记录状态均拒绝。
没有打开搜索面板、重置筛选、写入账号数据或输出 VIEWSTATE 内容。

加载扩展 **0.17.28** 并刷新 Library 页，Desktop/Core 不变。用新 F4 dry run
完成最终现场验证；之前任务不重启、不重新武装。控制台监听器与 unload 警告
没有提供账号完整性拒绝的直接证据，不作为本次修复目标。

## 实际 DOM 补丁：Chrome Bridge 0.17.27

用户提供的 `main_tableRecordHeader` 表格包含空首列表头、七格空白数据行，
以及最后的 `tablePagerGray tableBottomGray` 空占位行（单格 `colspan="7"`）。
0.17.25/26 错将这行当成异常数据行，导致 `ACCOUNT_LIMITS_UNVERIFIED`。
0.17.27 / record parser 0.1.5 精确接受该表的末尾空分页占位：必须具有
匹配列数的 colspan、两个已知 class，且无文本或任何交互控件。真正分页、
未知单格行仍拒绝；嵌套布局表不重复计数内部记录表。回归覆盖真实提供的
空表结构以及错误跨度、文本、链接、class 和表 ID 的拒绝场景。

重新加载 Chrome 扩展至 **0.17.27** 并刷新 Library 标签页即可，Desktop
仍为 0.19.2，Core 无需重启。空记录仍不代表预约成功。现场用一个新的未来
F4 只读演练验证，不重用过期授权。

## 后续补丁：Chrome Bridge 0.17.26 登录超时恢复

日期查询、空位检索的配置阶段和预约记录读取遇到 Library 登录失效时，
在同一个工作流创建的标签页上最多重新进入一次固定的 Library Secure 入口。
保留原来的导航期限，不无限重试；跳转中的 SSO 和 Portal 登录/MFA 页面不被打断。
恢复后重新核对原目标日期、设施与记录。不会填写账号密码、操作 MFA、点击
Search Record 或重放 Submit，也不会重新启用已过期授权。

本补丁只需在 Chrome 重新加载扩展 0.17.26 并刷新 HKU 标签页，Desktop 插件
仍为 0.19.2，无需重装或重启 Core。现场用一个新的未来 F4 只读演练验证；
若 SSO 会话也过期，仍须手动登录，再创建新任务。不要切换 live 绕过拒绝。

用户确认 My Booking Record 默认页只有六列表头和空白行，无“无记录”文案。
旧解析要求日期记录行或明确 No records 文案，因此拒绝了空表，触发
ACCOUNT_LIMITS_UNVERIFIED。该次 dry run 写入 0，已过期，不重新武装。

## 修复范围

- 识别默认空表：已加载完成、记录页路径、Logout 证据、无 URL 查询参数，
  精确表头 Start Date/Time、End Date/Time、Location、Floor、Facility、Status，
  以及全空数据行。仅一个匹配表，无未知记录、分页、筛选、加载或错误标记。
- 不点击 Search Record，不修改筛选或账号记录。筛选控件存在、隐藏筛选值、
  多页记录和未知表格继续拒绝；没有绕过账号完整性保护。
- 记录页导航等待明确 loading 标记消失，再返回解析结果。
- F3 运行通过 rule_id 关联同一规则：分别展示准备时间、检查开始时间和
  运行启动时间。建议候选仅在 outcome=suggestion_ready 且候选 ID 唯一
  匹配 suggested_candidate_id 时展示，不取任意候选或猜测历史目标。
- F3 只读标记来自 shadow_only/read_only；规则显示 run_count/max_runs，
  运行显示写入数，预约尝试/成功计数只用于 F4。旧迁移状态有中文解释。

## 自动测试和状态

144 Python 测试、77 Desktop 测试、12 浏览器合成脚本全部通过，0.19.2 安装包已生成并核对版本。
默认空表、加载/筛选/分页/错误/重复表/未知行拒绝都有合成覆盖。
没有触发真实预约、修改规则/授权或安装插件；现场复验仍待用户确认。

## 只需一次最小复验

1. 用户退出 Desktop 后安装 0.19.2。Chrome 重新加载扩展 0.17.25，刷新
   Library 标签页；本批未改 Core 运行逻辑，无须重启 Core。
2. 刷新任务状态中心，查看已有 F3 运行，确认显示只读、Discussion Room 2
   20:00–21:00 候选；检查开始 14:01 与准备 13:59 分开。无需重跑 F3。
3. Admin 只启用 F4 dry run，创建一个新的未来授权，核对现场日期、空位、
   一小时时段和空目标日记录，选中并明确 Arm。不要恢复过期授权。
4. 预期 dry_run_ready_no_submission、attempt_count=0、写入 0，无点选/表单/
   Submit。若仍拒绝，保留错误码；不要切换 live 绕过。
5. 关闭 F4 runtime，按实际结果标记并生成脱敏报告。无需重测 Moodle 或 F1/F2。
