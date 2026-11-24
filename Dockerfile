FROM python:3.13-slim

ARG PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt -i ${PYPI_MIRROR}

COPY main.py config_template.ini /app/
COPY api /app/api
COPY resource /app/resource

# 创建非 root 运行用户、配置文件目录并授予工作目录读写权限
RUN groupadd -r chaoxing && \
    useradd -r -g chaoxing -d /app -s /sbin/nologin chaoxing && \
    mkdir -p /config && \
    cp config_template.ini /config/config.ini && \
    chown -R chaoxing:chaoxing /app /config

# 定义卷，用户可以挂载自己的配置文件
VOLUME /config

USER chaoxing

# 使用配置文件启动应用
ENTRYPOINT ["python3", "main.py", "-c", "/config/config.ini"]
