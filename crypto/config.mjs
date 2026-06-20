// Параметры токена $RAMIN. Меняй здесь — больше нигде ничего трогать не нужно.
export const TOKEN = {
  name: "Ramin",
  symbol: "RAMIN",
  // Описание и сайт для метаданных (видно в кошельках/эксплорерах).
  description: "RAMIN — мем-токен барана-маскота из нашего Telegram-казино. 🐏 Не финсовет, чистый мем.",
  // Файл лого в папке assets/. Лучше PNG 512x512. По умолчанию — SVG-заглушка.
  imageFile: "assets/logo.svg",

  decimals: 6, // 6 — стандарт мемкоинов на Solana (как pump.fun / USDC)
  supply: 1_000_000_000, // 1 млрд токенов (целое число, без учёта decimals)

  // Отозвать право чеканить новые токены после выпуска (фиксированная эмиссия → честный вайб).
  revokeMintAuthority: true,
  // Отозвать freeze authority (никто не сможет заморозить чужие кошельки).
  revokeFreezeAuthority: true,

  // Доп. ссылки в метаданных (можно оставить пустыми).
  external_url: "",
};

// RPC: переключение сети одной переменной окружения.
//   NETWORK=devnet  npm run launch   → тест, бесплатно
//   NETWORK=mainnet npm run launch   → боевая сеть, реальный газ
export const NETWORK = process.env.NETWORK || "devnet";

export const RPC = {
  devnet: process.env.RPC_URL || "https://api.devnet.solana.com",
  mainnet: process.env.RPC_URL || "https://api.mainnet-beta.solana.com",
}[NETWORK];

if (!RPC) {
  throw new Error(`Неизвестная сеть NETWORK=${NETWORK}. Используй devnet или mainnet.`);
}
