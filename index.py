import requests
import time

def get_public_ip():
    try:
        response = requests.get('https://ipinfo.io/ip')
        if response.status_code == 200:
            return response.text.strip()
        else:
            print(f"获取公网IP地址失败，状态码: {response.status_code}")
            return None
    except Exception as e:
        print(f"获取公网IP地址失败: {e}")
        return None

def send_ip_to_domain(ip_address, domain_url):
    headers = {
        'Content-Type': 'application/json'
    }
    data = {
        'ip_address': ip_address
    }

    try:
        response = requests.post(domain_url, headers=headers, json=data)
        if response.status_code == 200:
            print(f"IP地址 {ip_address} 成功发送到 {domain_url}")
        else:
            print(f"发送失败，状态码: {response.status_code}")
    except Exception as e:
        print(f"请求失败: {e}")


def main():
    domain = "http://127.0.0.1:5000/receive_ip"  # 替换为实际的域名

    while True:
        ip = get_public_ip()
        if ip:
            send_ip_to_domain(ip, domain)
        else:
            print("无法获取公网IP地址")

        # 每隔一小时（3600秒）休眠
        time.sleep(3)

# 主程序
if __name__ == "__main__":
    main()