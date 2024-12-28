import asyncio
import base64
import os
from typing import Any, Tuple
import httpx
import cv2
import numpy as np
from paddleocr import PaddleOCR

# 模型路径检查
rec_model_path = './en_PP-OCRv4_rec_infer'
if os.name == 'posix':  # Linux 和 macOS 使用 posix
    rec_model_path = './en_PP-OCRv4_rec_infer'  # 识别模型文件夹路径

if not os.path.exists(rec_model_path):
    raise FileNotFoundError(f"模型路径不存在: {rec_model_path}")

# 初始化 OCR
ocr = PaddleOCR(rec_model_dir=rec_model_path, lang='en', use_angle_cls=True, show_log=False)


class ImageTextRecognizer:
    @staticmethod
    def preprocess_image(imgBase: str) -> np.ndarray:
        """图像预处理：白底灰字，增强对比度，适配艺术字体"""
        # 解码 Base64 图片
        image_data = base64.b64decode(imgBase)
        image_array = np.frombuffer(image_data, np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

        # 转为灰度图像
        gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # 拉普拉斯滤波器进行锐化
        laplacian = cv2.Laplacian(gray_image, cv2.CV_64F)
        sharpened_image = cv2.convertScaleAbs(laplacian)

        # 合并锐化图像和原图像
        enhanced_image = cv2.addWeighted(gray_image, 0.8, sharpened_image, 0.2, 0)

        # 自适应阈值分割（处理艺术字体和复杂背景）
        binary_image = cv2.adaptiveThreshold(
            enhanced_image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 5
        )

        # 边缘增强（针对艺术字体）
        kernel = np.ones((2, 2), np.uint8)
        enhanced_image = cv2.dilate(binary_image, kernel, iterations=1)

        return enhanced_image

    @staticmethod
    async def recognize_text(imgBase: str) -> Tuple[str, bool]:
        """识别文字内容"""
        try:
            # 图像预处理
            processed_image = ImageTextRecognizer.preprocess_image(imgBase)

            # 转换为 OCR 输入格式
            success, image_data = cv2.imencode('.png', processed_image)
            if not success:
                return "图像编码失败", False
            image_data = image_data.tobytes()

            # 使用 PaddleOCR 进行识别
            results = await asyncio.to_thread(ocr.ocr, image_data, det=False, rec=True)
            if not results or not results[0]:
                return "未能识别到任何文本", False

            # 提取识别结果
            line_text, confidence = results[0][0]
            recognized_text = line_text.strip().replace(" ", "")  # 去掉多余空格

            return recognized_text, True
        except Exception as e:
            return f"识别错误: {str(e)}", False


class TwoCaptchaImageSolver:
    BASE_URL = "https://api.2captcha.com"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=10)

    async def solvecaps(self, imgBase: str) -> Tuple[str, bool]:
        """本地使用 PaddleOCR 进行验证码识别"""
        try:
            recognized_text, success = await ImageTextRecognizer.recognize_text(imgBase)
            if not success:
                return recognized_text, False
            return recognized_text, True
        except Exception as e:
            return f"本地识别错误: {str(e)}", False

    async def solve(self, image: str) -> Tuple[str, bool]:
        """通过 2Captcha 平台进行验证码识别"""
        try:
            captcha_data = {
                "clientKey": self.api_key,
                "softId": 4706,
                "task": {
                    "type": "ImageToTextTask",
                    "body": image,
                    "phrase": False,
                    "case": True,
                    "numeric": 4,
                    "math": False,
                    "minLength": 6,
                    "maxLength": 6,
                    "comment": "Pay close attention to the letter case.",
                },
            }

            resp = await self.client.post(f"{self.BASE_URL}/createTask", json=captcha_data)
            resp.raise_for_status()
            data = resp.json()

            if data.get("errorId") == 0:
                return await self.get_captcha_result(data.get("taskId"))
            return data.get("errorDescription"), False

        except httpx.HTTPStatusError as err:
            pass
        except Exception as err:
            pass

    async def get_captcha_result(self, task_id: int | str) -> Tuple[str, bool, int | str]:
        """获取验证码结果"""
        for _ in range(10):
            try:
                resp = await self.client.post(
                    f"{self.BASE_URL}/getTaskResult",
                    json={"clientKey": self.api_key, "taskId": task_id},
                )
                resp.raise_for_status()
                result = resp.json()

                if result.get("errorId") != 0:
                    return result.get("errorDescription"), False, task_id

                if result.get("status") == "ready":
                    return result["solution"].get("text", ""), True, task_id

                await asyncio.sleep(3)

            except httpx.HTTPStatusError as err:
                pass
            except Exception as err:
                pass

        return "超时未获得结果", False

    async def report_bad(self, task_id: str | int) -> Tuple[Any, bool]:
        """报告错误的验证码结果"""
        try:
            resp = await self.client.post(
                f"{self.BASE_URL}/reportIncorrect",
                json={"clientKey": self.api_key, "taskId": task_id},
            )
            resp.raise_for_status()
            return resp.json(), True
        except httpx.HTTPStatusError as err:
            pass
        except Exception as err:
            pass
