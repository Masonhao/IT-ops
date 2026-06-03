#!/usr/bin/env python3
"""
企业运维管理系统 - 全功能测试用例
覆盖所有模块的API测试
"""
import requests
import json
import sys
from datetime import datetime, timedelta
import time as _time

BASE_URL = "http://127.0.0.1:5003"
TEST_TS = int(_time.time())

class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"

class TestRunner:
    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False  # 忽略环境代理变量
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.created_ids = {
            "equipment": [],
            "inspection": [],
            "worklog": [],
            "report": [],
            "user": []
        }
        # 初始化为None避免后续引用错误
        self.equip_id = None
        self.equip_id2 = None
        self.insp_id = None
        self.insp_id2 = None
        self.wl_id = None
        self.wl_id2 = None
        self.report_daily_id = None
        self.report_weekly_id = None
        self.report_monthly_id = None
        self.user_id = None

    def log(self, msg, color=""):
        print(f"{color}{msg}{Colors.RESET}")

    def _do_request(self, method, full_url, data=None):
        """发送请求，处理database locked重试"""
        import time
        last_err = None
        for attempt in range(3):
            try:
                if method == "GET":
                    return self.session.get(full_url, timeout=15, allow_redirects=False)
                elif method == "POST":
                    return self.session.post(full_url, json=data, timeout=15)
                elif method == "PUT":
                    return self.session.put(full_url, json=data, timeout=15)
                elif method == "DELETE":
                    return self.session.delete(full_url, timeout=15)
            except Exception as e:
                last_err = e
                time.sleep(0.3)
        raise last_err

    def test(self, name, method, url, expected_status, data=None, check_fn=None):
        """执行单个测试用例（含重试）"""
        full_url = f"{BASE_URL}{url}"
        import time
        for attempt in range(3):
            try:
                resp = self._do_request(method, full_url, data)
                ok = resp.status_code == expected_status
                if check_fn and ok:
                    try:
                        body = resp.json() if resp.text else {}
                    except:
                        body = resp.text
                    ok = check_fn(body)

                if ok:
                    self.passed += 1
                    self.log(f"  [PASS] {name} ({resp.status_code})", Colors.GREEN)
                    return resp
                else:
                    # 检查是否是database locked，是则重试
                    body_text = resp.text if resp.text else ""
                    if "database is locked" in body_text or "locked" in body_text.lower():
                        time.sleep(0.3)
                        continue
                    self.failed += 1
                    body_preview = body_text[:200]
                    err = f"  [FAIL] {name} — 期望 {expected_status}, 实际 {resp.status_code}, 响应: {body_preview}"
                    self.log(err, Colors.RED)
                    self.errors.append(err)
                    return resp
            except Exception as e:
                if attempt < 2 and ("locked" in str(e).lower() or "timeout" in str(e).lower()):
                    time.sleep(0.3)
                    continue
                self.failed += 1
                err = f"  [FAIL] {name} — 异常: {e}"
                self.log(err, Colors.RED)
                self.errors.append(err)
                return None
        return None

    def section(self, title):
        print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
        print(f"{Colors.BLUE}  {title}{Colors.RESET}")
        print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
        print(f"{Colors.BLUE}  测试总结{Colors.RESET}")
        print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")
        print(f"  总计: {total}  通过: {Colors.GREEN}{self.passed}{Colors.RESET}  失败: {Colors.RED}{self.failed}{Colors.RESET}")
        if self.failed > 0:
            print(f"\n{Colors.RED}失败项:{Colors.RESET}")
            for e in self.errors:
                print(f"  {e}")
        print()
        return self.failed == 0


# ==================== 开始测试 ====================
runner = TestRunner()

today = datetime.now().strftime("%Y-%m-%d")
tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

# ========== 1. 认证模块 ==========
runner.section("1. 认证模块")

# 1.1 未登录访问受保护页面 — 应返回302重定向到登录页
runner.test("1.1 未登录GET首页应302重定向", "GET", "/", 302)
runner.test("1.2 未登录GET设备页面应302重定向", "GET", "/equipment", 302)
runner.test("1.3 未登录GET API应重定向到登录", "GET", "/api/equipment", 302)

# 1.4 登录失败
runner.test("1.4 错误密码登录", "POST", "/login", 401,
            {"username": "admin", "password": "wrong"})
runner.test("1.5 空用户名密码", "POST", "/login", 400,
            {"username": "", "password": ""})

# 1.6 正常登录
resp = runner.test("1.6 admin正常登录", "POST", "/login", 200,
                   {"username": "admin", "password": "admin"},
                   lambda b: b.get("message") == "登录成功" and b.get("user", {}).get("role") == "admin")

# 1.7 获取当前用户信息
runner.test("1.7 获取当前用户", "GET", "/api/me", 200,
            check_fn=lambda b: b.get("username") == "admin" and b.get("role") == "admin")

# ========== 2. 设备台账模块 ==========
runner.section("2. 设备台账模块")

# 使用随机编号避免历史数据冲突
resp = runner.test("2.1 创建网络设备", "POST", "/api/equipment", 201,
                   {
                       "equip_no": f"SW-TEST-{TEST_TS}",
                       "name": "华为核心交换机",
                       "equip_type": "network",
                       "brand": "华为",
                       "model": "S12700E",
                       "location": "机房A",
                       "ip_address": "192.168.1.1",
                       "status": "normal",
                       "specs": "48口万兆+4口40G",
                       "responsible": "张三",
                       "remark": "核心业务交换机"
                   })
if resp and resp.status_code == 201:
    runner.equip_id = resp.json().get("id")
    runner.created_ids["equipment"].append(runner.equip_id)

# 创建设备2（安全设备）
resp2 = runner.test("2.2 创建安全设备", "POST", "/api/equipment", 201,
                    {
                        "equip_no": f"FW-TEST-{TEST_TS}",
                        "name": "山石防火墙",
                        "equip_type": "security",
                        "brand": "山石网科",
                        "model": "SG-6000-E2300",
                        "location": "机房B",
                        "ip_address": "10.0.0.1",
                        "status": "normal",
                        "specs": "吞吐10Gbps",
                        "responsible": "李四",
                        "remark": "互联网出口防火墙"
                    })
if resp2 and resp2.status_code == 201:
    runner.equip_id2 = resp2.json().get("id")
    runner.created_ids["equipment"].append(runner.equip_id2)

# 2.3 查询设备列表
runner.test("2.3 查询设备列表", "GET", "/api/equipment", 200,
            check_fn=lambda b: isinstance(b, list))

# 2.4 按类型筛选
runner.test("2.4 按网络类型筛选", "GET", "/api/equipment?equip_type=network", 200,
            check_fn=lambda b: isinstance(b, list))

# 2.5 更新设备
if runner.equip_id:
    runner.test("2.5 更新设备状态", "PUT", f"/api/equipment/{runner.equip_id}", 200,
                {"status": "warning", "remark": "例行维护中"})

# ========== 3. 巡检模板模块 ==========
runner.section("3. 巡检模板模块")

runner.test("3.1 获取网络设备巡检模板", "GET", "/api/inspection/templates?equip_type=network", 200,
            check_fn=lambda b: isinstance(b, list) and len(b) > 0)
runner.test("3.2 获取安全设备巡检模板", "GET", "/api/inspection/templates?equip_type=security", 200,
            check_fn=lambda b: isinstance(b, list))
runner.test("3.3 获取全部巡检模板", "GET", "/api/inspection/templates", 200,
            check_fn=lambda b: isinstance(b, list))

# ========== 4. 每日巡检模块 ==========
runner.section("4. 每日巡检模块")

# 4.1 创建巡检记录
if runner.equip_id:
    resp = runner.test("4.1 创建网络设备巡检", "POST", "/api/inspections", 201,
                       {
                           "inspection_date": today,
                           "equipment_id": runner.equip_id,
                           "items": [
                               {"name": "CPU使用率", "checked": True, "result": "35%"},
                               {"name": "内存使用率", "checked": True, "result": "42%"},
                               {"name": "端口状态", "checked": True, "result": "全部正常"}
                           ],
                           "status": "normal",
                           "abnormal_items": "",
                           "action_taken": "无",
                           "duration_minutes": 15,
                           "remark": "例行巡检"
                       })
    if resp and resp.status_code == 201:
        runner.insp_id = resp.json().get("id")
        runner.created_ids["inspection"].append(runner.insp_id)

    # 创建异常巡检记录
    resp_ab = runner.test("4.2 创建异常巡检", "POST", "/api/inspections", 201,
                          {
                              "inspection_date": today,
                              "equipment_id": runner.equip_id2,
                              "items": [
                                  {"name": "CPU使用率", "checked": True, "result": "95%"},
                                  {"name": "日志检查", "checked": True, "result": "发现异常连接"}
                              ],
                              "status": "abnormal",
                              "abnormal_items": "CPU使用率过高，发现异常连接尝试",
                              "action_taken": "已重启防火墙服务，更新安全策略",
                              "duration_minutes": 45,
                              "remark": "紧急处理"
                          })
    if resp_ab and resp_ab.status_code == 201:
        runner.insp_id2 = resp_ab.json().get("id")
        runner.created_ids["inspection"].append(runner.insp_id2)

    # 4.3 查询巡检列表
    runner.test("4.3 查询今日巡检列表", "GET", f"/api/inspections?date={today}", 200,
                check_fn=lambda b: isinstance(b, list) and len(b) >= 1)

    runner.test("4.4 按状态筛选-正常", "GET", "/api/inspections?status=normal", 200,
                check_fn=lambda b: isinstance(b, list))

    runner.test("4.5 按状态筛选-异常", "GET", "/api/inspections?status=abnormal", 200,
                check_fn=lambda b: isinstance(b, list))

    # 4.5 查看巡检详情
    if runner.insp_id:
        runner.test("4.6 查看巡检详情", "GET", f"/api/inspections/{runner.insp_id}", 200,
                    check_fn=lambda b: b.get("id") == runner.insp_id and "items" in b)

    # 4.6 更新巡检
    if runner.insp_id:
        runner.test("4.7 更新巡检耗时", "PUT", f"/api/inspections/{runner.insp_id}", 200,
                    {"duration_minutes": 20, "remark": "更新备注"})

# ========== 5. 工作日志模块 ==========
runner.section("5. 工作日志模块")

# 5.1 创建工作日志
resp = runner.test("5.1 创建维修工作日志", "POST", "/api/worklogs", 201,
                   {
                       "log_date": today,
                       "work_type": "repair",
                       "title": "核心交换机端口故障处理",
                       "content": "发现核心交换机GigabitEthernet0/0/24端口down，经排查为光纤模块故障。更换光模块后恢复正常。",
                       "equipment_ids": str(runner.equip_id) if runner.equip_id else "",
                       "inspection_ids": str(runner.insp_id) if runner.insp_id else "",
                       "duration_minutes": 60,
                       "status": "submitted"
                   })
if resp and resp.status_code == 201:
    runner.wl_id = resp.json().get("id")
    runner.created_ids["worklog"].append(runner.wl_id)

# 创建第二个日志
resp2 = runner.test("5.2 创建变更工作日志", "POST", "/api/worklogs", 201,
                    {
                        "log_date": today,
                        "work_type": "change",
                        "title": "防火墙策略调整",
                        "content": "根据安全要求，调整防火墙入站策略，屏蔽高风险端口。",
                        "equipment_ids": str(runner.equip_id2) if runner.equip_id2 else "",
                        "duration_minutes": 30,
                        "status": "submitted"
                    })
if resp2 and resp2.status_code == 201:
    runner.wl_id2 = resp2.json().get("id")
    runner.created_ids["worklog"].append(runner.wl_id2)

# 5.3 查询工作日志
runner.test("5.3 查询今日日志", "GET", f"/api/worklogs?date={today}", 200,
            check_fn=lambda b: isinstance(b, list) and len(b) >= 2)

runner.test("5.4 按类型筛选-维修", "GET", "/api/worklogs?work_type=repair", 200,
            check_fn=lambda b: isinstance(b, list))

# 5.5 查看日志详情（含关联数据）
if runner.wl_id and runner.equip_id and runner.insp_id:
    runner.test("5.5 查看日志详情(含关联设备/巡检)", "GET", f"/api/worklogs/{runner.wl_id}", 200,
                check_fn=lambda b: b.get("equipments") is not None and b.get("inspections") is not None)

# 5.6 更新日志
if runner.wl_id:
    runner.test("5.6 更新日志状态", "PUT", f"/api/worklogs/{runner.wl_id}", 200,
                {"status": "draft", "duration_minutes": 75})

# ========== 6. 日报模块 ==========
runner.section("6. 日报模块")

resp = runner.test("6.1 创建日报", "POST", "/api/reports", 201,
                   {
                       "report_type": "daily",
                       "report_date": today,
                       "title": f"{today} 运维日报",
                       "summary": "今日完成核心交换机巡检和防火墙策略调整。",
                       "completed_tasks": "1. 核心交换机例行巡检\n2. 防火墙安全策略更新\n3. 处理端口故障一例",
                       "pending_tasks": "1. 无线AP固件升级\n2. 服务器存储扩容评估",
                       "problems": "核心交换机端口偶发down，需持续关注",
                       "equipment_ids": f"{runner.equip_id},{runner.equip_id2}" if runner.equip_id and runner.equip_id2 else "",
                       "work_log_ids": f"{runner.wl_id},{runner.wl_id2}" if runner.wl_id and runner.wl_id2 else "",
                       "duration_total": 90,
                       "status": "submitted"
                   })
if resp and resp.status_code == 201:
    runner.report_daily_id = resp.json().get("id")
    runner.created_ids["report"].append(runner.report_daily_id)

runner.test("6.2 查询日报列表", "GET", "/api/reports/list?report_type=daily", 200,
            check_fn=lambda b: isinstance(b, list) and len(b) >= 1)

if runner.report_daily_id:
    runner.test("6.3 查看日报详情(含关联)", "GET", f"/api/reports/{runner.report_daily_id}", 200,
                check_fn=lambda b: "work_logs" in b)

    runner.test("6.4 更新日报", "PUT", f"/api/reports/{runner.report_daily_id}", 200,
                {"duration_total": 120, "problems": "已解决"})

# ========== 7. 周报模块 ==========
runner.section("7. 周报模块")

week_str = datetime.now().strftime("%Y-W%W")
resp = runner.test("7.1 创建周报", "POST", "/api/reports", 201,
                   {
                       "report_type": "weekly",
                       "report_date": week_str,
                       "title": f"第{week_str}周 运维周报",
                       "summary": "本周网络运行稳定，完成2次巡检，处理1起故障。",
                       "completed_tasks": "完成全部设备巡检\n处理防火墙异常连接\n更新安全策略",
                       "pending_tasks": "下周进行无线AP升级",
                       "problems": "无重大故障",
                       "duration_total": 480,
                       "status": "submitted"
                   })
if resp and resp.status_code == 201:
    runner.report_weekly_id = resp.json().get("id")
    runner.created_ids["report"].append(runner.report_weekly_id)

runner.test("7.2 查询周报列表", "GET", "/api/reports/list?report_type=weekly", 200,
            check_fn=lambda b: isinstance(b, list) and len(b) >= 1)

# ========== 8. 月报模块 ==========
runner.section("8. 月报模块")

month_str = datetime.now().strftime("%Y-%m")
resp = runner.test("8.1 创建月报", "POST", "/api/reports", 201,
                   {
                       "report_type": "monthly",
                       "report_date": month_str,
                       "title": f"{month_str} 运维月报",
                       "summary": "本月网络整体运行平稳，可用率99.9%。",
                       "completed_tasks": "完成全部月度巡检\n处理3起故障\n完成防火墙策略更新",
                       "pending_tasks": "下月进行核心交换机固件升级",
                       "problems": "无",
                       "duration_total": 2000,
                       "status": "submitted"
                   })
if resp and resp.status_code == 201:
    runner.report_monthly_id = resp.json().get("id")
    runner.created_ids["report"].append(runner.report_monthly_id)

runner.test("8.2 查询月报列表", "GET", "/api/reports/list?report_type=monthly", 200,
            check_fn=lambda b: isinstance(b, list) and len(b) >= 1)

# ========== 9. 统计查询模块 ==========
runner.section("9. 统计查询模块")

runner.test("9.1 工程师今日工作统计", "GET", f"/api/stats/engineer-work?date={today}", 200,
            check_fn=lambda b: "work_logs" in b and "inspections" in b)

if runner.equip_id:
    runner.test("9.2 设备维护历史", "GET", f"/api/stats/equipment-history?equipment_id={runner.equip_id}", 200,
                check_fn=lambda b: "inspections" in b and "work_logs" in b)

# ========== 10. 用户管理模块 ==========
runner.section("10. 用户管理模块")

# 10.1 查询用户列表
runner.test("10.1 查询用户列表", "GET", "/api/users", 200,
            check_fn=lambda b: isinstance(b, list) and len(b) >= 1)

# 10.2 创建新用户（使用时间戳避免与历史数据冲突）
test_user = f"testeng_{TEST_TS}"
resp = runner.test("10.2 创建工程师用户", "POST", "/api/users", 201,
                   {
                       "username": test_user,
                       "password": "123456",
                       "real_name": "测试工程师",
                       "role": "engineer",
                       "permissions": "report_daily,worklog"
                   })
if resp and resp.status_code == 201:
    runner.user_id = resp.json().get("id")
    runner.created_ids["user"].append(runner.user_id)

# 10.3 查询单个用户
if runner.user_id:
    runner.test("10.3 查询用户详情", "GET", f"/api/users/{runner.user_id}", 200,
                check_fn=lambda b: b.get("username") == test_user)

    # 10.4 更新用户权限
    runner.test("10.4 更新用户权限", "PUT", f"/api/users/{runner.user_id}", 200,
                {"permissions": "report_daily,worklog,equipment", "real_name": "测试工程师-改"})

    # 10.5 禁用用户
    runner.test("10.5 禁用用户", "PUT", f"/api/users/{runner.user_id}", 200,
                {"is_active": 0})

# ========== 11. 权限控制测试 ==========
runner.section("11. 权限控制测试")

# 权限测试前先启用engineer1
if runner.user_id:
    runner.test("10.6 启用engineer1", "PUT", f"/api/users/{runner.user_id}", 200,
                {"is_active": 1})

# 11.1 登出admin
runner.test("11.1 admin登出应重定向", "GET", "/logout", 302)

# 11.2 用test_user登录（只有日报和工作日志权限）
runner.test("11.2 test_user登录", "POST", "/login", 200,
            {"username": test_user, "password": "123456"})

# 11.3 GET设备列表是开放查询（仅要求登录），工程师也可查看
runner.test("11.3 test_user访问设备列表(开放查询)", "GET", "/api/equipment", 200)

# 11.4 engineer1无权访问用户管理
runner.test("11.4 engineer1访问用户列表应403", "GET", "/api/users", 403)

# 11.5 engineer1可以访问工作日志
runner.test("11.5 engineer1访问工作日志", "GET", "/api/worklogs", 200)

# 11.6 engineer1可以访问日报
runner.test("11.6 engineer1访问日报列表", "GET", "/api/reports/list?report_type=daily", 200)

# 11.7 engineer1无权访问周报（没授权）
runner.test("11.7 engineer1访问周报应403", "GET", "/api/reports/list?report_type=weekly", 403)

# 重新登录admin做清理
runner.session.get(f"{BASE_URL}/logout", timeout=15)
runner.test("11.8 admin重新登录", "POST", "/login", 200,
            {"username": "admin", "password": "admin"})

# ========== 12. 清理测试数据 ==========
runner.section("12. 清理测试数据")

for rid in reversed(runner.created_ids["report"]):
    runner.test(f"12.x 删除报表 {rid}", "DELETE", f"/api/reports/{rid}", 200)

for wid in reversed(runner.created_ids["worklog"]):
    runner.test(f"12.x 删除日志 {wid}", "DELETE", f"/api/worklogs/{wid}", 200)

for iid in reversed(runner.created_ids["inspection"]):
    runner.test(f"12.x 删除巡检 {iid}", "DELETE", f"/api/inspections/{iid}", 200)

for eid in reversed(runner.created_ids["equipment"]):
    runner.test(f"12.x 删除设备 {eid}", "DELETE", f"/api/equipment/{eid}", 200)

for uid in reversed(runner.created_ids["user"]):
    runner.test(f"12.x 删除用户 {uid}", "DELETE", f"/api/users/{uid}", 200)

# ========== 总结 ==========
success = runner.summary()
sys.exit(0 if success else 1)
