# 🌅 Dawn Extension Bot [v1.6]

 - fork：https://github.com/Jaammerr/The-Dawn-Bot
 - 在https://github.com/wyq000 大佬的基础上升级1.6
 - 支持本地识别不需要配置(2captcha 或 anticaptcha)

## 📋 Table of Contents
- [功能](#-功能)
- [运行环境](#-运行环境)
- [安装指南](#-安装指南)
- [配置文件](#%EF%B8%8F-配置文件)
- [使用方法](#-使用方法)
- [常见问题](#-常见问题)

## 🚀 功能

- ✨ **账号管理**
  - ✅ 自动账号注册和登录
  - 📧 智能账号重新验证系统
  - 🛡️ 基于令牌的身份验证存储
  
- 🤖 **自动化**
  - 🌾 智能任务完成
  - 💰 优化积分获取
  - 🔄 高级保活机制
  
- 📊 **统计与导出**
  - 📈 全面的账号统计
  - 📉 被封账号跟踪
  - 📋 未验证账号监控
  
- 🔒 **安全**
  - 🧩 高级验证码破解集成
  - 🌐 支持代理 (HTTP/SOCKS5)
  - 🔐 安全的邮箱集成

## 💻 运行环境

- Python 3.11 或更高版本
- 稳定的互联网连接
- 有效的邮箱账号
- 可用代理 (HTTP/SOCKS5)
- 验证码服务订阅 (2captcha 或 anticaptcha)

## 🛠️ 安装指南

1. **克隆仓库**
   ```bash
   git clone [仓库链接]
   ```

2. **创建虚拟环境**
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # Windows
   source venv/bin/activate      # Unix/MacOS
   ```

3. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

## ⚙️ 配置文件

### 📁 settings.yaml 示例

```yaml
# 核心配置
threads: 30                    # 并发线程数 (最小值: 1)
keepalive_interval: 120        # 保活信号间隔 (秒)
referral_codes:               # 支持多个推荐码
  - ""                        # 在此添加推荐码

# 邮件重定向设置
redirect_settings:
  enabled: false              # 启用/禁用邮件重定向
  email: "test@gmail.com"     # 重定向邮箱地址
  password: "password"        # 邮箱密码
  imap_server: "imap.gmail.com"
  use_proxy: true            # 是否为邮件操作使用代理

# 验证码配置
captcha_module: 2captcha      # 选择: '2captcha' 或 'anticaptcha'
two_captcha_api_key: ""       # 2captcha API 密钥
anti_captcha_api_key: ""      # Anticaptcha API 密钥

# 启动延迟设置
delay_before_start:
  min: 2                      # 最小启动延迟 (秒)
  max: 3                      # 最大启动延迟 (秒)

# 邮箱提供商设置
imap_settings:
  # 全球服务商
  gmail.com: imap.gmail.com
  yahoo.com: imap.mail.yahoo.com
  outlook.com: imap-mail.outlook.com
  hotmail.com: imap-mail.outlook.com
  icloud.com: imap.mail.me.com
  
  # 地区服务商
  mail.ru: imap.mail.ru
  rambler.ru: imap.rambler.ru
  gmx.com: imap.gmx.com
  onet.pl: imap.poczta.onet.pl
```

### 📁 输入文件结构
#### accounts/register.txt
```
email:password
email:password
```

#### accounts/farm.txt
```
email:password
email:password
```

#### accounts/reverify.txt
```
email:password
email:password
```

#### proxies/proxies.txt
```
http://user:pass@ip:port
http://ip:port:user:pass
socks5://user:pass@ip:port
```

## 🚀 使用方法

1. 按上述描述配置所有必要文件
2. 启动机器人：
   ```bash
   python run.py
   ```

## ⚠️ 注意事项

- 🕒 建议的保活间隔：120 秒
- 📧 Gmail 用户：请使用应用专用密码
- 🔄 未验证的账号可以使用注册模块重新验证
- 💾 授权令牌存储在本地数据库中
- 🤖 不再需要 ！！！！！！！！！外部验证码服务 (2captcha 或 anticaptcha) 

## 🔧 常见问题

### 常见问题及解决方法

#### 📧 邮箱验证失败
- 检查 settings.yaml 中的 IMAP 设置
- 检查邮箱提供商的安全设置
- Gmail 用户确保已启用应用专用密码

#### 🧩 验证码问题
- 自动本地识别
- 自动本地识别
- 自动本地识别

#### 🌐  代理问题
- 验证代理格式
- 检查代理是否可用
- 确保代理认证信息正确
