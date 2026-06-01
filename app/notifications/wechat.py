import requests
from app.config import WECHAT_WEBHOOK


def send_wechat_message(content: str):
    if not WECHAT_WEBHOOK:
        print("未配置企业微信 Webhook，跳过发送")
        return False

    data = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }

    try:
        response = requests.post(WECHAT_WEBHOOK, json=data, timeout=10)
        result = response.json()
        print("企业微信发送结果：", result)
        return result.get("errcode") == 0
    except Exception as e:
        print("企业微信发送失败：", e)
        return False


def build_warning_message(red_list, yellow_list):
    lines = []
    lines.append("【智能库存预警提醒】")
    lines.append(f"红色预警：{len(red_list)} 条")
    lines.append(f"黄色预警：{len(yellow_list)} 条")
    lines.append("")

    if red_list:
        lines.append("🔴 红色预警：已缺货")
        for item in red_list[:10]:
            lines.append(
                f"- {item.get('存货', item.get('商品名称', '未知商品'))} "
                f"｜SKU：{item.get('存货编码', '')} "
                f"｜可用量：{item.get('系统计算可用量', '')} "
                f"｜建议调货：{item.get('建议调货量', '')}"
            )
        lines.append("")

    if yellow_list:
        lines.append("🟡 黄色预警：库存不足，建议调货")
        for item in yellow_list[:10]:
            lines.append(
                f"- {item.get('存货', item.get('商品名称', '未知商品'))} "
                f"｜SKU：{item.get('存货编码', '')} "
                f"｜可售天数：{item.get('可售天数', '')} "
                f"｜建议调货：{item.get('建议调货量', '')}"
            )

    return "\n".join(lines)


def build_daily_summary_message(summary):
    return f"""【库存预警每日汇总】

预警总数：{summary.get("warning_total", 0)}
红色预警：{summary.get("red_count", 0)}
黄色预警：{summary.get("yellow_count", 0)}
正常库存：{summary.get("normal_count", 0)}
建议调货总量：{summary.get("suggest_total", 0)}

请及时查看库存预警后台。"""