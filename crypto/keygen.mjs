// Управление кошельком: создать новый или показать адрес/баланс.
//   node keygen.mjs          → создаёт keypair.json (если его ещё нет) и печатает адрес
//   node keygen.mjs balance  → показывает баланс в текущей сети (NETWORK)
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createUmi } from "@metaplex-foundation/umi-bundle-defaults";
import { generateSigner, keypairIdentity, sol } from "@metaplex-foundation/umi";
import { RPC, NETWORK } from "./config.mjs";

const KEYPAIR_PATH = "keypair.json";
const umi = createUmi(RPC);

function loadKeypair() {
  const secret = new Uint8Array(JSON.parse(readFileSync(KEYPAIR_PATH, "utf8")));
  return umi.eddsa.createKeypairFromSecretKey(secret);
}

const cmd = process.argv[2];

if (cmd === "balance") {
  const kp = loadKeypair();
  const bal = await umi.rpc.getBalance(kp.publicKey);
  console.log(`Сеть:    ${NETWORK}`);
  console.log(`Адрес:   ${kp.publicKey}`);
  console.log(`Баланс:  ${Number(bal.basisPoints) / 1e9} SOL`);
} else {
  if (existsSync(KEYPAIR_PATH)) {
    const kp = loadKeypair();
    console.log("keypair.json уже существует — использую его.");
    console.log(`Адрес: ${kp.publicKey}`);
  } else {
    const kp = generateSigner(umi);
    // Сохраняем секретный ключ в формате массива байт (совместим с Solana CLI / Phantom import).
    writeFileSync(KEYPAIR_PATH, JSON.stringify(Array.from(kp.secretKey)));
    console.log("✅ Создан новый кошелёк → keypair.json (НЕ коммить его!)");
    console.log(`Адрес: ${kp.publicKey}`);
    console.log("\nПополни этот адрес SOL перед запуском:");
    console.log("  • devnet:  solana airdrop / https://faucet.solana.com");
    console.log("  • mainnet: ~0.05 SOL на газ и загрузку метаданных");
  }
}
