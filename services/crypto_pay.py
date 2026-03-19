import asyncio
import logging
from crypto_pay_api_sdk import cryptopay
from config import CRYPTOBOT_TOKEN

logger = logging.getLogger(__name__)

class CryptoPayService:
    def __init__(self):
        self.client = cryptopay.Crypto(token=CRYPTOBOT_TOKEN)

    async def create_invoice(self, asset: str, amount: str, payload: str, description: str):
        """Создаёт инвойс асинхронно, оборачивая синхронный вызов."""
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None,
                lambda: self.client.createInvoice(
                    asset=asset,
                    amount=amount,
                    params={"payload": payload, "description": description}
                )
            )
        except Exception as e:
            logger.error(f"Ошибка создания инвойса: {e}")
            raise

    async def get_invoice(self, invoice_id: int):
        """Получает инвойс по ID асинхронно."""
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None,
                lambda: self.client.getInvoices(params={"invoice_ids": [invoice_id]})
            )
        except Exception as e:
            logger.error(f"Ошибка получения инвойса: {e}")
            raise

crypto_pay_service = CryptoPayService()