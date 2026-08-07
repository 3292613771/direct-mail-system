import os
os.environ['TZ'] = 'Asia/Shanghai'
try:
    import time
    time.tzset()
except:
    pass

from flask import Flask, request, redirect, session
import imaplib
import email
import re
import html
import json
from email.header import decode_header
from email.utils import parsedate_to_datetime
import uuid
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'direct-mail-2024'

# ===== 配置 =====
ACCOUNTS_FILE = "accounts.txt"
LINKS_FILE = "links.json"
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '060910')
DEFAULT_DAYS = 30
DOMAIN = "qqmailapi.zeabur.app"

# ===== 读取账号（支持两种格式） =====
def load_accounts():
    accounts = {}
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                if "----" in line:
                    parts = line.split("----")
                    if len(parts) == 2:
                        email_addr = parts[0].strip()
                        auth_code = parts[1].strip()
                        if '@' not in email_addr:
                            email_addr = email_addr + "@qq.com"
                        accounts[email_addr] = auth_code
                else:
                    parts = line.split()
                    if len(parts) >= 4:
                        emails = parts[0:3]
                        auth_code = parts[3]
                        for em in emails:
                            if '@' not in em:
                                em = em + "@qq.com"
                            accounts[em] = auth_code
                    elif len(parts) == 2:
                        em = parts[0]
                        auth_code = parts[1]
                        if '@' not in em:
                            em = em + "@qq.com"
                        accounts[em] = auth_code
    except Exception as e:
        print(f"读取账号失败: {e}")
    return accounts

ACCOUNTS = load_accounts()
print(f"已加载 {len(ACCOUNTS)} 个邮箱")

# ===== 邮件解析（纯文本，不提取验证码） =====
def decode_str(s):
    if not s:
        return ""
    try:
        decoded_parts = []
        for part, charset in decode_header(s):
            if isinstance(part, bytes):
                if charset:
                    decoded_parts.append(part.decode(charset, errors='replace'))
                else:
                    decoded_parts.append(part.decode('utf-8', errors='replace'))
            else:
                decoded_parts.append(str(part))
        return ' '.join(decoded_parts)
    except:
        return str(s)

def get_mail_content(msg):
    """获取邮件纯文本内容"""
    try:
        all_parts = []
        if msg.is_multipart():
            for part in msg.walk():
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        text = payload.decode(charset, errors='replace')
                    except:
                        text = payload.decode('utf-8', errors='replace')
                    if text.strip():
                        all_parts.append((part.get_content_type(), text))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                try:
                    text = payload.decode(charset, errors='replace')
                except:
                    text = payload.decode('utf-8', errors='replace')
                if text.strip():
                    all_parts.append((msg.get_content_type(), text))
        
        # 优先纯文本
        for content_type, text in all_parts:
            if content_type == "text/plain":
                return text.strip()
        
        # 没有纯文本就用HTML
        for content_type, text in all_parts:
            if content_type == "text/html":
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = html.unescape(text)
                text = re.sub(r'\s+', ' ', text)
                return text.strip()
        
        return "无法解析邮件内容"
    except:
        return "解析失败"

def get_latest_mails(email_addr, limit=1):
    if email_addr not in ACCOUNTS:
        return {'error': '邮箱未绑定'}
    
    auth_code = ACCOUNTS[email_addr]
    mail = None
    
    try:
        mail = imaplib.IMAP4_SSL("imap.qq.com")
        mail.login(email_addr, auth_code)
        
        all_mail_ids = []
        folder_info = []
        
        try:
            mail.select("INBOX")
            status, data = mail.search(None, "ALL")
            if data[0]:
                for mid in data[0].split():
                    all_mail_ids.append(mid)
                    folder_info.append("INBOX")
        except:
            pass
        
        spam_folders = ["垃圾箱", "[Gmail]/Spam", "Spam", "Junk"]
        for folder in spam_folders:
            try:
                mail.select(folder)
                status, data = mail.search(None, "ALL")
                if data[0]:
                    for mid in data[0].split():
                        all_mail_ids.append(mid)
                        folder_info.append(folder)
                break
            except:
                continue
        
        if not all_mail_ids:
            return []
        
        seen = set()
        unique_ids = []
        unique_folders = []
        for mid, folder in zip(all_mail_ids, folder_info):
            mid_str = mid.decode() if isinstance(mid, bytes) else str(mid)
            if mid_str not in seen:
                seen.add(mid_str)
                unique_ids.append(mid)
                unique_folders.append(folder)
        
        sorted_pairs = sorted(zip(unique_ids, unique_folders), key=lambda x: int(x[0]))
        latest_pairs = sorted_pairs[-limit:]
        
        mails = []
        for mail_id, folder in reversed(latest_pairs):
            try:
                mail_id_str = mail_id.decode() if isinstance(mid, bytes) else str(mail_id)
                mail.select(folder)
                _, msg_data = mail.fetch(mail_id, "(RFC822)")
                
                for part in msg_data:
                    if isinstance(part, tuple):
                        msg = email.message_from_bytes(part[1])
                        date_str = msg.get("Date", "")
                        send_time = ""
                        try:
                            if date_str:
                                dt = parsedate_to_datetime(date_str)
                                send_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            send_time = date_str[:30]
                        
                        mails.append({
                            'sender': decode_str(msg.get("From", "未知")),
                            'subject': decode_str(msg.get("Subject", "无主题")),
                            'content': get_mail_content(msg),
                            'time': send_time,
                            'folder': folder
                        })
                        break
            except:
                continue
        
        return mails
    except Exception as e:
        return {'error': f'连接失败：{str(e)}'}
    finally:
        if mail:
            try:
                mail.close()
            except:
                pass
            try:
                mail.logout()
            except:
                pass

# ===== 链接管理 =====
def load_links():
    try:
        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_links(data):
    with open(LINKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ===== 登录 =====
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect('/admin')
        return '<h2>密码错误</h2><a href="/login">重试</a>'
    
    return '''
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>登录</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family:Arial;max-width:400px;margin:100px auto;padding:20px;">
        <h2>🔐 后台登录</h2>
        <form method="post">
            <input type="password" name="password" placeholder="请输入密码" style="width:100%;padding:12px;font-size:16px;margin:10px 0;border:2px solid #ddd;border-radius:8px;">
            <button type="submit" style="width:100%;padding:12px;background:#4CAF50;color:white;border:none;font-size:16px;cursor:pointer;border-radius:8px;">登录</button>
        </form>
    </body>
    </html>
    '''

# ===== 后台 =====
@app.route('/admin')
def admin():
    if not session.get('logged_in'):
        return redirect('/login')
    
    links = load_links()
    
    total = len(ACCOUNTS)
    used_emails = set()
    for data in links.values():
        used_emails.add(data['email'])
    used = len(used_emails)
    
    link_list = ""
    for link_id, data in links.items():
        status = '✅' if data['status'] == 'active' else '⛔'
        expire_time = datetime.strptime(data['expire_at'], "%Y-%m-%d %H:%M:%S")
        is_expired = datetime.now() > expire_time
        if is_expired and data['status'] == 'active':
            status = '⏰'
        
        link_url = f"https://{DOMAIN}/m/{link_id}"
        link_list += f"""
        <tr>
            <td><a href="{link_url}" target="_blank">{link_url}</a></td>
            <td>{data['email']}</td>
            <td>{data['created_at']}</td>
            <td>{data['expire_at']}</td>
            <td>{status}</td>
            <td>{data.get('query_count', 0)}</td>
            <td>
                <a href="/api/disable/{link_id}" onclick="return confirm('确定禁用？')" style="color:red;">禁用</a>
                <a href="/api/delete/{link_id}" onclick="return confirm('确定删除？')" style="color:red;margin-left:10px;">删除</a>
            </td>
        </tr>
        """
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>直连邮箱系统</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family:Arial;max-width:1200px;margin:20px auto;padding:20px;">
        <h2>📧 直连邮箱系统</h2>
        
        <div style="background:#e8f5e9;padding:15px;border-radius:8px;margin:15px 0;">
            <b>📊 统计：</b>总邮箱 {total} | 已生成 {used} | 可用 {total - used}
        </div>
        
        <div style="background:#fff3cd;padding:15px;border-radius:8px;margin:15px 0;">
            <h3>➕ 批量生成链接</h3>
            <form action="/api/batch_create" method="post">
                <textarea name="emails" placeholder="每行一个邮箱" rows="8" style="width:100%;padding:10px;font-size:14px;"></textarea>
                <br>
                <select name="days">
                    <option value="7">7天</option>
                    <option value="30" selected>30天</option>
                    <option value="90">90天</option>
                    <option value="365">365天</option>
                </select>
                <br><br>
                <button type="submit" style="padding:10px 30px;background:#4CAF50;color:white;border:none;cursor:pointer;font-size:16px;border-radius:8px;">批量生成</button>
            </form>
        </div>
        
        <hr>
        <h3>🔗 链接列表（共 {len(links)} 个）</h3>
        <table border="1" cellpadding="8" style="width:100%;border-collapse:collapse;">
        <tr><th>链接</th><th>邮箱</th><th>创建时间</th><th>过期时间</th><th>状态</th><th>查询次数</th><th>操作</th></tr>
        {link_list if link_list else '<tr><td colspan="7">暂无链接</td></tr>'}
        </table>
    </body>
    </html>
    '''

# ===== 批量生成 =====
@app.route('/api/batch_create', methods=['POST'])
def batch_create():
    if not session.get('logged_in'):
        return redirect('/login')
    
    emails_text = request.form.get('emails', '')
    days = int(request.form.get('days', 30))
    
    emails = []
    for line in emails_text.strip().split('\n'):
        email_addr = line.strip()
        if email_addr:
            if '@' not in email_addr:
                email_addr = email_addr + "@qq.com"
            emails.append(email_addr)
    
    if not emails:
        return "请至少输入一个邮箱", 400
    
    links = load_links()
    now = datetime.now()
    results = []
    
    for email_addr in emails:
        if email_addr not in ACCOUNTS:
            results.append(f"{email_addr}----未绑定")
            continue
        
        existing = None
        for lid, ldata in links.items():
            if ldata['email'] == email_addr and ldata['status'] == 'active':
                existing = lid
                break
        
        if existing:
            link_url = f"https://{DOMAIN}/m/{existing}"
            results.append(f"{email_addr}----{link_url}")
            continue
        
        link_id = str(uuid.uuid4())[:8]
        links[link_id] = {
            'link_id': link_id,
            'email': email_addr,
            'created_at': now.strftime("%Y-%m-%d %H:%M:%S"),
            'expire_at': (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"),
            'status': 'active',
            'query_count': 0
        }
        link_url = f"https://{DOMAIN}/m/{link_id}"
        results.append(f"{email_addr}----{link_url}")
    
    save_links(links)
    
    return '<pre style="font-size:14px;">' + '\n'.join(results) + '</pre><br><a href="/admin">返回后台</a>'

# ===== 禁用 =====
@app.route('/api/disable/<link_id>')
def disable_link(link_id):
    if not session.get('logged_in'):
        return redirect('/login')
    links = load_links()
    if link_id in links:
        links[link_id]['status'] = 'disabled'
        save_links(links)
    return redirect('/admin')

# ===== 删除 =====
@app.route('/api/delete/<link_id>')
def delete_link(link_id):
    if not session.get('logged_in'):
        return redirect('/login')
    links = load_links()
    if link_id in links:
        del links[link_id]
        save_links(links)
    return redirect('/admin')

# ===== 查看邮件（只显示最新1封，完整内容） =====
@app.route('/m/<link_id>')
def view_mail(link_id):
    links = load_links()
    
    if link_id not in links:
        return "<h2>❌ 链接不存在</h2>", 404
    
    link_data = links[link_id]
    now = datetime.now()
    expire_time = datetime.strptime(link_data['expire_at'], "%Y-%m-%d %H:%M:%S")
    
    if now > expire_time:
        return "<h2>⏰ 链接已过期</h2>", 410
    
    if link_data['status'] != 'active':
        return "<h2>⛔ 链接已被禁用</h2>", 403
    
    link_data['query_count'] = link_data.get('query_count', 0) + 1
    save_links(links)
    
    email_addr = link_data['email']
    result = get_latest_mails(email_addr, limit=1)
    
    if isinstance(result, dict) and 'error' in result:
        return f"<h2>❌ {result['error']}</h2>"
    
    if not result:
        return f'''
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"><title>{email_addr}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family:Arial;max-width:600px;margin:20px auto;padding:20px;text-align:center;">
            <h2>📭 暂无邮件</h2>
            <p>{email_addr}</p>
        </body>
        </html>
        '''
    
    mail = result[0]
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>{email_addr}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 20px auto; padding: 20px; background: #f5f5f5; }}
            .header {{ background: white; padding: 15px; border-radius: 8px; margin-bottom: 15px; text-align: center; }}
            .refresh {{ display: inline-block; padding: 10px 30px; background: #4CAF50; color: white; text-decoration: none; border-radius: 8px; margin-top: 10px; }}
            .mail-box {{ border:1px solid #ddd; border-radius:8px; padding:15px; background:white; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>📧 {email_addr}</h2>
            <p style="color:#999;">{mail.get('time', '')}</p>
            <a href="/m/{link_id}" class="refresh">🔄 刷新邮件</a>
        </div>
        <div class="mail-box">
            <div style="margin-bottom:10px;"><b>发件人：</b>{mail['sender']}</div>
            <div style="margin-bottom:10px;"><b>主题：</b>{mail['subject']}</div>
            <div style="border-top:1px solid #eee;padding-top:10px;white-space:pre-wrap;word-break:break-word;">
                {mail['content']}
            </div>
        </div>
    </body>
    </html>
    '''

@app.route('/')
def index():
    return redirect('/admin')

if __name__ == '__main__':
    print("=" * 50)
    print("直连邮箱系统启动")
    print(f"域名: {DOMAIN}")
    print(f"已绑定 {len(ACCOUNTS)} 个邮箱")
    print("=" * 50)
    app.run(host='0.0.0.0', port=8080)
