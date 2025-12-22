#!/usr/bin/env python3
"""
诊断脚本：排查 quantTrader 不执行交易的问题

使用方法:
    python diagnose_trader.py --config config.json
"""
import argparse
import json
import sys
from datetime import datetime

import requests
from pymongo import MongoClient


def print_section(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check_config(config_path: str):
    """检查配置文件"""
    print_section("1. 检查配置文件")
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        
        print(f"✓ 配置文件读取成功: {config_path}")
        print(f"  - API Base URL: {cfg.get('api_base_url')}")
        print(f"  - Token (前10位): {cfg.get('api_token', '')[:10]}...")
        print(f"  - Poll Interval: {cfg.get('poll_interval')} 秒")
        print(f"  - Broker: {cfg.get('broker', 'simulated')}")
        return cfg
    except Exception as e:
        print(f"✗ 配置文件错误: {e}")
        return None


def check_api_connection(cfg: dict):
    """检查 API 连接"""
    print_section("2. 检查 API 连接")
    
    base_url = cfg.get("api_base_url", "").rstrip("/")
    token = cfg.get("api_token", "")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    
    try:
        # 测试 /trader/signals 端点
        url = f"{base_url}/trader/signals"
        resp = requests.get(url, headers=headers, params={"limit": 10}, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            signal_count = len(data.get("data", []))
            print(f"✓ API 连接成功")
            print(f"  - Endpoint: {url}")
            print(f"  - Status Code: {resp.status_code}")
            print(f"  - 获取到信号数: {signal_count}")
            return data.get("data", [])
        elif resp.status_code == 401:
            print(f"✗ 认证失败 (401): Token 可能过期或无效")
            print(f"  Response: {resp.text}")
            return None
        else:
            print(f"✗ API 请求失败")
            print(f"  Status Code: {resp.status_code}")
            print(f"  Response: {resp.text}")
            return None
            
    except requests.exceptions.ConnectionError:
        print(f"✗ 无法连接到 API 服务器")
        print(f"  URL: {base_url}")
        print(f"  请检查: 1) 服务器是否运行 2) URL 是否正确 3) 网络连接")
        return None
    except Exception as e:
        print(f"✗ API 连接错误: {e}")
        return None


def check_signals_in_db(mongo_uri: str, user_id: str = None):
    """检查 MongoDB 中的信号状态"""
    print_section("3. 检查 MongoDB 中的信号")
    
    try:
        client = MongoClient(mongo_uri)
        db = client.get_default_database()
        signals_coll = db["trade_signals"]
        
        # 构建查询条件
        query = {}
        if user_id:
            query["user_id"] = user_id
        
        # 统计各种状态的信号
        print("信号统计:")
        for status in ["pending", "retry_pending", "submitted", "filled", "failed"]:
            count_query = {**query, "status": status}
            count = signals_coll.count_documents(count_query)
            print(f"  - {status}: {count}")
        
        # 检查符合 Trader 条件的信号
        trader_query = {
            "is_executable": True,
            "mode": "live",
            "status": {"$in": ["pending", "retry_pending"]},
        }
        if user_id:
            trader_query["user_id"] = user_id
        
        matching_signals = list(signals_coll.find(trader_query).limit(5))
        print(f"\n符合 Trader 执行条件的信号: {len(matching_signals)}")
        
        if matching_signals:
            print("\n最近的可执行信号:")
            for sig in matching_signals[:3]:
                print(f"  - Order ID: {sig.get('order_id')}")
                print(f"    Symbol: {sig.get('symbol')}")
                print(f"    Action: {sig.get('action')}")
                print(f"    Size: {sig.get('size')}")
                print(f"    Status: {sig.get('status')}")
                print(f"    is_executable: {sig.get('is_executable')}")
                print(f"    mode: {sig.get('mode')}")
                print(f"    Created: {datetime.fromtimestamp(sig.get('timestamp', 0))}")
                print()
        else:
            print("\n⚠ 没有符合条件的信号!")
            print("可能原因:")
            print("  1. 信号缺少 is_executable=True 字段")
            print("  2. 信号缺少 mode='live' 字段")
            print("  3. 信号状态不是 'pending' 或 'retry_pending'")
            print("  4. user_id 不匹配")
            
            # 检查最近的信号（忽略条件）
            recent_query = {}
            if user_id:
                recent_query["user_id"] = user_id
            recent_signals = list(signals_coll.find(recent_query).sort("timestamp", -1).limit(3))
            
            if recent_signals:
                print("\n最近的信号（忽略执行条件）:")
                for sig in recent_signals:
                    print(f"  - Order ID: {sig.get('order_id')}")
                    print(f"    Status: {sig.get('status')}")
                    print(f"    is_executable: {sig.get('is_executable', 'MISSING')}")
                    print(f"    mode: {sig.get('mode', 'MISSING')}")
                    print()
        
        client.close()
        return matching_signals
        
    except Exception as e:
        print(f"✗ MongoDB 连接失败: {e}")
        return None


def check_trader_loop_logic():
    """检查 Trader Loop 的执行逻辑"""
    print_section("4. Trader Loop 执行逻辑检查")
    
    print("Trader 执行流程:")
    print("  1. 每隔 poll_interval 秒轮询一次")
    print("  2. 调用 API: GET /trader/signals")
    print("  3. 对每个信号调用 broker.place_order()")
    print("  4. 更新信号状态为 'submitted'")
    print("  5. 上报执行结果到 /trader/executions")
    
    print("\n⚠ 常见问题:")
    print("  - 日志级别设置为 INFO 以上，看不到 'Fetched signals' 消息")
    print("  - API 返回空列表，但没有打印日志（只有非空才打印）")
    print("  - 信号处理过程中抛出异常，但被捕获了")
    
    print("\n✓ 建议:")
    print("  1. 检查 Trader 日志输出，查看是否有错误")
    print("  2. 将 log_level 设置为 'DEBUG' 以获取更详细的日志")
    print("  3. 检查 broker.place_order() 是否抛出异常")


def main():
    parser = argparse.ArgumentParser(description="诊断 quantTrader 连接和执行问题")
    parser.add_argument("--config", required=True, help="quantTrader 配置文件路径")
    parser.add_argument("--mongo-uri", help="MongoDB 连接 URI (可选)")
    parser.add_argument("--user-id", help="用户 ID (可选)")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("  quantTrader 诊断工具")
    print("=" * 60)
    
    # 1. 检查配置
    cfg = check_config(args.config)
    if not cfg:
        print("\n✗ 配置文件检查失败，无法继续")
        sys.exit(1)
    
    # 2. 检查 API 连接
    signals = check_api_connection(cfg)
    
    # 3. 检查 MongoDB（如果提供了连接信息）
    if args.mongo_uri:
        db_signals = check_signals_in_db(args.mongo_uri, args.user_id)
    else:
        print_section("3. MongoDB 检查")
        print("⚠ 未提供 --mongo-uri，跳过数据库检查")
        print("提示: 添加 --mongo-uri 参数可检查数据库中的信号状态")
    
    # 4. 执行逻辑检查
    check_trader_loop_logic()
    
    # 总结
    print_section("诊断总结")
    
    if signals is not None and len(signals) > 0:
        print("✓ API 可以返回信号，Trader 应该能够执行")
        print(f"  发现 {len(signals)} 个待执行信号")
    elif signals is not None and len(signals) == 0:
        print("⚠ API 连接正常，但没有待执行的信号")
        print("  可能原因:")
        print("  1. 信号已经被执行或处理")
        print("  2. 信号缺少必要字段 (is_executable, mode)")
        print("  3. 信号状态不是 'pending' 或 'retry_pending'")
        print("\n  建议: 使用 insert_test_signal.py 插入测试信号")
    else:
        print("✗ API 连接失败，Trader 无法获取信号")
        print("  请先解决 API 连接问题")
    
    print("\n下一步:")
    print("  1. 如果 API 返回信号但 Trader 不执行，检查 Trader 日志")
    print("  2. 将配置中的 log_level 改为 'DEBUG'")
    print("  3. 重启 Trader 并观察详细日志输出")
    print("  4. 查看是否有异常被捕获")


if __name__ == "__main__":
    main()
