from datetime import datetime, timedelta
from typing import Tuple, Any, Optional, Literal

import pytz
from loguru import logger
from loader import config, file_operations
from models import Account, OperationResult, StatisticData

from .api import DawnExtensionAPI
from utils import EmailValidator, LinkExtractor
from database import Accounts
from .exceptions.base import APIError, SessionRateLimited, CaptchaSolvingFailed, APIErrorType


class Bot(DawnExtensionAPI):
    def __init__(self, account: Account):
        super().__init__(account)

    async def get_captcha_data(self) -> Tuple[str, Any, Optional[Any]]:
        for _ in range(5):
            try:
                puzzle_id = await self.get_puzzle_id()
                image = await self.get_puzzle_image(puzzle_id)

                logger.info(
                    f"账户: {self.account_data.email} | 获取到验证码图片，正在解析..."
                )
                answer, solved, *rest = await self.solve_puzzle1(image)

                if solved and len(answer) == 6:
                    logger.success(
                        f"账户: {self.account_data.email} | 验证码已解析: {answer}"
                    )
                    return puzzle_id, answer, rest[0] if rest else None

                if len(answer) != 6 and rest:
                    await self.report_invalid_puzzle(rest[0])

                if len(answer) > 30:
                    logger.error(
                        f"账户: {self.account_data.email} | 无法解析验证码: {answer} | 正在重试..."
                    )
                else:
                    logger.error(
                        f"账户: {self.account_data.email} | 验证码解析错误: 答案不正确 | 正在重试..."
                    )

            except SessionRateLimited:
                raise

            except Exception as e:
                logger.error(
                    f"账户: {self.account_data.email} | 解析验证码时出错: {str(e)} | 正在重试..."
                )

        raise CaptchaSolvingFailed("连续5次尝试后无法解析验证码")

    async def clear_account_and_session(self) -> None:
        if await Accounts.get_account(email=self.account_data.email):
            await Accounts.delete_account(email=self.account_data.email)
        self.session = self.setup_session()

    @staticmethod
    async def handle_invalid_account(email: str, password: str, reason: Literal["unverified", "banned"]) -> None:
        if reason == "unverified":
            logger.error(f"账户: {email} | 邮箱未验证，请运行重新验证模块 | 已从农场移除")
            await file_operations.export_unverified_email(email, password)

        else:
            logger.error(f"账户: {email} | 账户已被封禁 | 已从农场移除")
            await file_operations.export_banned_email(email, password)

        for account in config.accounts_to_farm:
            if account.email == email:
                config.accounts_to_farm.remove(account)

    async def process_reverify_email(self, link_sent: bool = False) -> OperationResult:
        task_id = None

        try:
            result = await EmailValidator(
                self.account_data.imap_server if not config.redirect_settings.enabled else config.redirect_settings.imap_server,
                self.account_data.email if not config.redirect_settings.enabled else config.redirect_settings.email,
                self.account_data.password if not config.redirect_settings.enabled else config.redirect_settings.password
            ).validate(None if config.redirect_settings.enabled and not config.redirect_settings.use_proxy else self.account_data.proxy)
            if not result["status"]:
                logger.error(f"账户: {self.account_data.email} | 邮箱无效: {result['data']}")
                return OperationResult(
                    identifier=self.account_data.email,
                    data=self.account_data.password,
                    status=False,
                )

            logger.info(f"账户: {self.account_data.email} | 正在重新验证邮箱...")
            puzzle_id, answer, task_id = await self.get_captcha_data()

            if not link_sent:
                await self.resend_verify_link(puzzle_id, answer)
                logger.info(f"账户: {self.account_data.email} | 成功重新发送验证邮件，等待邮件中...")
                link_sent = True

                confirm_url = await LinkExtractor(
                    mode="re-verify",
                    imap_server=self.account_data.imap_server if not config.redirect_settings.enabled else config.redirect_settings.imap_server,
                    email=self.account_data.email if not config.redirect_settings.enabled else config.redirect_settings.email,
                    password=self.account_data.password if not config.redirect_settings.enabled else config.redirect_settings.password
                ).extract_link(
                    None if config.redirect_settings.enabled and not config.redirect_settings.use_proxy else self.account_data.proxy)

                if not confirm_url["status"]:
                    logger.error(f"账户: {self.account_data.email} | 未找到确认链接: {confirm_url['data']}")
                    return OperationResult(
                        identifier=self.account_data.email,
                        data=self.account_data.password,
                        status=False,
                    )

                logger.success(
                    f"账户: {self.account_data.email} | 找到确认链接，正在确认邮箱..."
                )

                response = await self.clear_request(url=confirm_url["data"])
                if response.status_code == 200:
                    logger.success(
                        f"账户: {self.account_data.email} | 邮箱确认成功"
                    )
                    return OperationResult(
                        identifier=self.account_data.email,
                        data=self.account_data.password,
                        status=True,
                    )

                logger.error(
                    f"账户: {self.account_data.email} | 邮箱确认失败"
                )

        except APIError as error:
            match error.error_type:
                case APIErrorType.INCORRECT_CAPTCHA:
                    logger.warning(f"账户: {self.account_data.email} | 验证码答案错误，重新解析...")
                    if task_id:
                        await self.report_invalid_puzzle(task_id)
                    return await self.process_reverify_email(link_sent=link_sent)

                case APIErrorType.EMAIL_EXISTS:
                    logger.warning(f"账户: {self.account_data.email} | 邮箱已存在")

                case APIErrorType.CAPTCHA_EXPIRED:
                    logger.warning(f"账户: {self.account_data.email} | 验证码已过期，重新解析...")
                    return await self.process_reverify_email(link_sent=link_sent)

                case APIErrorType.SESSION_EXPIRED:
                    logger.warning(f"账户: {self.account_data.email} | 会话已过期，重新登录...")
                    await self.clear_account_and_session()
                    return await self.process_reverify_email(link_sent=link_sent)

                case _:
                    logger.error(f"账户: {self.account_data.email} | 重新验证邮箱失败: {error}")

        except Exception as error:
            logger.error(
                f"账户: {self.account_data.email} | 重新验证邮箱失败: {error}"
            )

        return OperationResult(
            identifier=self.account_data.email,
            data=self.account_data.password,
            status=False,
        )

    async def process_registration(self) -> OperationResult:
        task_id = None

        try:
            result = await EmailValidator(
                self.account_data.imap_server if not config.redirect_settings.enabled else config.redirect_settings.imap_server,
                self.account_data.email if not config.redirect_settings.enabled else config.redirect_settings.email,
                self.account_data.password if not config.redirect_settings.enabled else config.redirect_settings.password
            ).validate(
                None if config.redirect_settings.enabled and not config.redirect_settings.use_proxy else self.account_data.proxy)
            if not result["status"]:
                logger.error(f"账户: {self.account_data.email} | 邮箱无效: {result['data']}")
                return OperationResult(
                    identifier=self.account_data.email,
                    data=self.account_data.password,
                    status=False,
                )

            logger.info(f"账户: {self.account_data.email} | 正在注册...")
            puzzle_id, answer, task_id = await self.get_captcha_data()

            await self.register(puzzle_id, answer)
            logger.info(
                f"账户: {self.account_data.email} | 注册成功，正在等待邮件..."
            )

            confirm_url = await LinkExtractor(
                mode="verify",
                imap_server=self.account_data.imap_server if not config.redirect_settings.enabled else config.redirect_settings.imap_server,
                email=self.account_data.email if not config.redirect_settings.enabled else config.redirect_settings.email,
                password=self.account_data.password if not config.redirect_settings.enabled else config.redirect_settings.password
            ).extract_link(
                None if config.redirect_settings.enabled and not config.redirect_settings.use_proxy else self.account_data.proxy)

            if not confirm_url["status"]:
                logger.error(f"账户: {self.account_data.email} | 未找到确认链接: {confirm_url['data']}")
                return OperationResult(
                    identifier=self.account_data.email,
                    data=self.account_data.password,
                    status=False,
                )

                logger.success(
                    f"账户: {self.account_data.email} | 找到确认链接，正在确认注册..."
                )

                response = await self.clear_request(url=confirm_url["data"])
                if response.status_code == 200:
                    logger.success(
                        f"账户: {self.account_data.email} | 注册确认成功"
                    )
                    return OperationResult(
                        identifier=self.account_data.email,
                        data=self.account_data.password,
                        status=True,
                    )

                logger.error(
                    f"账户: {self.account_data.email} | 注册确认失败"
                )


        except APIError as error:
            match error.error_type:
                case APIErrorType.INCORRECT_CAPTCHA:
                    logger.warning(f"账户: {self.account_data.email} | 验证码答案错误，重新解析...")
                    if task_id:
                        await self.report_invalid_puzzle(task_id)
                    return await self.process_registration()

                case APIErrorType.EMAIL_EXISTS:
                    logger.warning(f"账户: {self.account_data.email} | 邮箱已存在")

                case APIErrorType.DOMAIN_BANNED:
                    logger.warning(
                        f"账户: {self.account_data.email} | 邮箱域名 <{self.account_data.email.split('@')[1]}> 可能被禁止使用")

                case APIErrorType.DOMAIN_BANNED_2:
                    logger.warning(
                        f"账户: {self.account_data.email} | 邮箱域名 <{self.account_data.email.split('@')[1]}> 可能被禁止使用")

                case APIErrorType.CAPTCHA_EXPIRED:
                    logger.warning(f"账户: {self.account_data.email} | 验证码已过期，重新解析...")
                    return await self.process_registration()

                case _:
                    logger.error(f"账户: {self.account_data.email} | 注册失败: {error}")

        except Exception as error:
            logger.error(
                f"账户: {self.account_data.email} | 注册失败: {error}"
            )

        return OperationResult(
            identifier=self.account_data.email,
            data=self.account_data.password,
            status=False,
        )

    @staticmethod
    def get_sleep_until(blocked: bool = False) -> datetime:
        duration = (
            timedelta(minutes=10)
            if blocked
            else timedelta(seconds=config.keepalive_interval)
        )
        return datetime.now(pytz.UTC) + duration

    async def process_farming(self) -> None:
        try:
            db_account_data = await Accounts.get_account(email=self.account_data.email)

            if db_account_data and db_account_data.session_blocked_until:
                if await self.handle_sleep(db_account_data.session_blocked_until):
                    return

            if not db_account_data or not db_account_data.headers:
                if not await self.login_new_account():
                    return

            elif not await self.handle_existing_account(db_account_data):
                return

            await self.perform_farming_actions()

        except SessionRateLimited:
            await self.handle_session_blocked()


        except APIError as error:
            match error.error_type:
                case APIErrorType.UNVERIFIED_EMAIL:
                    await self.handle_invalid_account(self.account_data.email, self.account_data.password, "unverified")

                case APIErrorType.BANNED:
                    await self.handle_invalid_account(self.account_data.email, self.account_data.password, "banned")

                case APIErrorType.SESSION_EXPIRED:
                    logger.warning(f"账户: {self.account_data.email} | 会话已过期，重新登录...")
                    await self.clear_account_and_session()
                    return await self.process_farming()

                case _:
                    logger.error(f"账户: {self.account_data.email} | 执行任务失败: {error}")


        except Exception as error:
            logger.error(
                f"账户: {self.account_data.email} | 执行任务失败: {error}"
            )

        return

    async def process_get_user_info(self) -> StatisticData:
        try:
            db_account_data = await Accounts.get_account(email=self.account_data.email)

            if db_account_data and db_account_data.session_blocked_until:
                if await self.handle_sleep(db_account_data.session_blocked_until):
                    return StatisticData(
                        success=False, referralPoint=None, rewardPoint=None
                    )

            if not db_account_data or not db_account_data.headers:
                if not await self.login_new_account():
                    return StatisticData(
                        success=False, referralPoint=None, rewardPoint=None
                    )

            elif not await self.handle_existing_account(db_account_data):
                return StatisticData(
                    success=False, referralPoint=None, rewardPoint=None
                )

            user_info = await self.user_info()
            logger.success(
                f"账户: {self.account_data.email} | 成功获取用户信息"
            )
            return StatisticData(
                success=True,
                referralPoint=user_info["referralPoint"],
                rewardPoint=user_info["rewardPoint"],
            )

        except SessionRateLimited:
            await self.handle_session_blocked()

        except APIError as error:
            match error.error_type:
                case APIErrorType.UNVERIFIED_EMAIL:
                    await self.handle_invalid_account(self.account_data.email, self.account_data.password, "unverified")

                case APIErrorType.BANNED:
                    await self.handle_invalid_account(self.account_data.email, self.account_data.password, "banned")

                case APIErrorType.SESSION_EXPIRED:
                    logger.warning(f"账户: {self.account_data.email} | 会话已过期，重新登录...")
                    await self.clear_account_and_session()
                    return await self.process_get_user_info()

                case _:
                    logger.error(
                        f"账户: {self.account_data.email} | 获取用户信息失败: {error}"
                    )

        except Exception as error:
            logger.error(
                f"账户: {self.account_data.email} | 获取用户信息失败: {error}"
            )

        return StatisticData(success=False, referralPoint=None, rewardPoint=None)

    async def process_complete_tasks(self) -> OperationResult:
        try:
            db_account_data = await Accounts.get_account(email=self.account_data.email)
            if db_account_data is None:
                if not await self.login_new_account():
                    return OperationResult(
                        identifier=self.account_data.email,
                        data=self.account_data.password,
                        status=False,
                    )
            else:
                await self.handle_existing_account(db_account_data)

            logger.info(f"账户: {self.account_data.email} | 正在完成任务...")
            await self.complete_tasks()

            logger.success(
                f"账户: {self.account_data.email} | 任务完成成功"
            )
            return OperationResult(
                identifier=self.account_data.email,
                data=self.account_data.password,
                status=True,
            )

        except Exception as error:
            logger.error(
                f"账户: {self.account_data.email} | 完成任务失败: {error}"
            )
            return OperationResult(
                identifier=self.account_data.email,
                data=self.account_data.password,
                status=False,
            )

    async def login_new_account(self):
        task_id = None

        try:
            logger.info(f"账户: {self.account_data.email} | 正在登录...")
            puzzle_id, answer, task_id = await self.get_captcha_data()

            await self.login(puzzle_id, answer)
            logger.info(f"账户: {self.account_data.email} | 登录成功")

            await Accounts.create_account(email=self.account_data.email, app_id=self.account_data.appid, headers=self.session.headers)
            return True

        except APIError as error:
            match error.error_type:
                case APIErrorType.INCORRECT_CAPTCHA:
                    logger.warning(f"账户: {self.account_data.email} | 验证码答案错误，正在重新解答...")
                    if task_id:
                        await self.report_invalid_puzzle(task_id)
                    return await self.login_new_account()

                case APIErrorType.UNVERIFIED_EMAIL:
                    await self.handle_invalid_account(self.account_data.email, self.account_data.password, "unverified")
                    return False

                case APIErrorType.BANNED:
                    await self.handle_invalid_account(self.account_data.email, self.account_data.password, "banned")
                    return False

                case APIErrorType.CAPTCHA_EXPIRED:
                    logger.warning(f"账户: {self.account_data.email} | 验证码已过期，正在重新解答...")
                    return await self.login_new_account()

                case _:
                    logger.error(f"账户: {self.account_data.email} | 登录失败: {error}")
                    return False

        except CaptchaSolvingFailed:
            sleep_until = self.get_sleep_until()
            await Accounts.set_sleep_until(self.account_data.email, sleep_until)
            logger.error(
                f"账户: {self.account_data.email} | 解答验证码失败超过 5 次，进入休眠..."
            )
            return False

        except Exception as error:
            logger.error(
                f"账户: {self.account_data.email} | 登录失败: {error}"
            )
            return False

    async def handle_existing_account(self, db_account_data) -> bool | None:
        if db_account_data.sleep_until and await self.handle_sleep(
            db_account_data.sleep_until
        ):
            return False

        self.session.headers = db_account_data.headers
        status, result = await self.verify_session()
        if not status:
            logger.warning(
                f"账户: {self.account_data.email} | 会话无效，正在重新登录: {result}"
            )
            await self.clear_account_and_session()
            return await self.process_farming()

        logger.info(f"账户: {self.account_data.email} | 使用现有会话")
        return True

    async def handle_session_blocked(self):
        await self.clear_account_and_session()
        logger.error(
            f"账户: {self.account_data.email} | 会话被限速 | 进入休眠..."
        )
        sleep_until = self.get_sleep_until(blocked=True)
        await Accounts.set_session_blocked_until(email=self.account_data.email, session_blocked_until=sleep_until, app_id=self.account_data.appid)

    async def handle_sleep(self, sleep_until):
        current_time = datetime.now(pytz.UTC)
        sleep_until = sleep_until.replace(tzinfo=pytz.UTC)

        if sleep_until > current_time:
            sleep_duration = (sleep_until - current_time).total_seconds()
            logger.debug(
                f"账户: {self.account_data.email} | 休眠直到下次操作 {sleep_until} (持续时间: {sleep_duration:.2f} 秒)"
            )
            return True

        return False

    async def close_session(self):
        try:
            await self.session.close()
        except Exception as error:
            logger.debug(
                f"账户: {self.account_data.email} | 关闭会话失败: {error}"
            )

    async def perform_farming_actions(self):
        try:
            await self.keepalive()
            logger.success(
                f"账户: {self.account_data.email} | 发送了保持连接请求"
            )

            user_info = await self.user_info()
            logger.info(
                f"账户: {self.account_data.email} | 总积分: {user_info['rewardPoint']['points']}"
            )

        except Exception as error:
            logger.error(
                f"账户: {self.account_data.email} | 执行农场操作失败: {error}"
            )

        finally:
            new_sleep_until = self.get_sleep_until()
            await Accounts.set_sleep_until(
                email=self.account_data.email, sleep_until=new_sleep_until
            )
