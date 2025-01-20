# Bilibili History Analyzer (获取B站历史记录并进行分析的工具)

由于b站历史只会显示最近几个月的，所以历史记录会慢慢过期，因此该项目用于获取、处理、分析和可视化哔哩哔哩用户的观看历史数据。它提供了完整的数据处理流程，从数据获取到可视化展示，并支持自动化运行和邮件通知。

## 配套前端请前往此项目[BiliHistoryFrontend](https://github.com/2977094657/BiliHistoryFrontend) 

## 主要功能

1. **数据获取与存储**
   - 自动获取B站观看历史记录
   - 按年/月/日层级存储数据
   - 支持增量更新，避免重复获取
   - 自动分类视频内容

2. **数据处理与分析**
   - 数据清洗和标准化
   - SQLite数据库存储
   - 视频分类统计
   - 观看时间分析

3. **可视化展示**
   - 生成年度观看热力图
   - 支持自定义热力图样式
   - 可配置图表尺寸和颜色

4. **自动化任务**
   - 支持定时任务调度
   - 自动数据同步
   - 错误重试机制
   - 邮件通知功能

5. **API接口**
   - RESTful API设计
   - 完整的接口文档
   - 支持多种查询方式

## 系统要求

- Python 3.8+
- SQLite 3
- 必要的Python包（见requirements.txt）

## 快速开始

1. **安装依赖**
```bash
pip install -r requirements.txt
```

2. **配置文件**

在 `config/config.yaml` 中配置以下信息：
```yaml
# B站用户认证
SESSDATA: "你的SESSDATA"

# 邮件通知配置
email:
  smtp_server: smtp.qq.com
  smtp_port: 587
  sender: "发件人邮箱"
  password: "邮箱授权码"
  receiver: "收件人邮箱"

# 服务器配置
server:
  host: "localhost"
  port: 8899
```

3. **运行程序**
```bash
python main.py
```

## API接口

基础URL: `http://localhost:8899`

### 部分主要接口
- `/BiliHistory2024/all`: 获取历史记录
- `/BiliHistory2024/search`: 搜索历史记录
- `/analysis/analyze`: 分析数据
- `/heatmap/generate_heatmap`: 生成热力图
- `/log/send-email`: 发送日志邮件

完整API文档访问：`http://localhost:8899/docs`

## 自动化任务配置

在 `config/scheduler_config.yaml` 中配置定时任务：
```yaml
tasks:
  fetch_history:
    schedule:
      type: "daily"
      time: "00:00"
  
  analyze_data:
    schedule:
      type: "chain"
    requires:
      - fetch_history
```

## 数据存储结构

```
output/
├── history_by_date/     # 原始历史数据
│   └── YYYY/MM/DD.json
├── cleaned_history/     # 清理后的数据
├── heatmap/            # 热力图输出
└── logs/               # 运行日志
```

## 安全说明

1. API请求限制：
   - 默认每秒1次请求
   - 可在配置文件中调整

2. Cookie安全：
   - 定期更新SESSDATA
   - 不要分享配置文件

## 常见问题

1. **Cookie经常失效**
   - 删除localStorage中的`ac_time_value`
   - 重新获取SESSDATA
   - 更新配置文件

## 贡献指南

1. Fork 项目
2. 创建特性分支
3. 提交更改
4. 发起 Pull Request

## 许可证

MIT License

## 致谢

- [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)
- 所有贡献者
