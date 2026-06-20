// Выпуск токена $RAMIN: загрузка метаданных → создание mint → чеканка эмиссии → отзыв прав.
//   NETWORK=devnet  node launch.mjs   (тест)
//   NETWORK=mainnet node launch.mjs   (боевая сеть, реальный газ)
import { readFileSync } from "node:fs";
import { basename } from "node:path";
import { createUmi } from "@metaplex-foundation/umi-bundle-defaults";
import { irysUploader } from "@metaplex-foundation/umi-uploader-irys";
import {
  generateSigner,
  keypairIdentity,
  percentAmount,
  createGenericFile,
} from "@metaplex-foundation/umi";
import {
  createFungible,
  mintV1,
  TokenStandard,
} from "@metaplex-foundation/mpl-token-metadata";
import { setAuthority, AuthorityType } from "@metaplex-foundation/mpl-toolbox";
import { none } from "@metaplex-foundation/umi";
import { TOKEN, RPC, NETWORK } from "./config.mjs";

const KEYPAIR_PATH = "keypair.json";

function step(msg) { console.log(`\n➡️  ${msg}`); }

// --- 1. Подключение и кошелёк ---------------------------------------------
const umi = createUmi(RPC).use(irysUploader());
const secret = new Uint8Array(JSON.parse(readFileSync(KEYPAIR_PATH, "utf8")));
const wallet = umi.eddsa.createKeypairFromSecretKey(secret);
umi.use(keypairIdentity(wallet));

console.log(`Сеть:   ${NETWORK}`);
console.log(`Кошелёк: ${wallet.publicKey}`);

const bal = await umi.rpc.getBalance(wallet.publicKey);
const balSol = Number(bal.basisPoints) / 1e9;
console.log(`Баланс: ${balSol} SOL`);
if (balSol < 0.02) {
  console.error("\n❌ Слишком мало SOL. Нужно минимум ~0.02–0.05 SOL на газ и метаданные.");
  process.exit(1);
}

if (NETWORK === "mainnet") {
  console.log("\n⚠️  MAINNET: будет потрачен реальный SOL и создан реальный токен.");
  console.log("    Ctrl+C в течение 5 секунд, чтобы отменить...");
  await new Promise((r) => setTimeout(r, 5000));
}

// --- 2. Загрузка лого и JSON-метаданных -----------------------------------
step("Загружаю лого...");
const imgBytes = readFileSync(TOKEN.imageFile);
const ext = TOKEN.imageFile.split(".").pop().toLowerCase();
const contentType = ext === "png" ? "image/png" : ext === "jpg" || ext === "jpeg" ? "image/jpeg" : "image/svg+xml";
const file = createGenericFile(imgBytes, basename(TOKEN.imageFile), { contentType });
const [imageUri] = await umi.uploader.upload([file]);
console.log(`   image: ${imageUri}`);

step("Загружаю JSON-метаданные...");
const metadataUri = await umi.uploader.uploadJson({
  name: TOKEN.name,
  symbol: TOKEN.symbol,
  description: TOKEN.description,
  image: imageUri,
  external_url: TOKEN.external_url || undefined,
});
console.log(`   metadata: ${metadataUri}`);

// --- 3. Создание mint + on-chain метаданных -------------------------------
step("Создаю токен (mint + metadata)...");
const mint = generateSigner(umi);
await createFungible(umi, {
  mint,
  name: TOKEN.name,
  symbol: TOKEN.symbol,
  uri: metadataUri,
  sellerFeeBasisPoints: percentAmount(0),
  decimals: TOKEN.decimals,
}).sendAndConfirm(umi);
console.log(`   mint address: ${mint.publicKey}`);

// --- 4. Чеканка всей эмиссии на свой кошелёк -------------------------------
step(`Чеканю ${TOKEN.supply.toLocaleString("ru")} ${TOKEN.symbol}...`);
const amount = BigInt(TOKEN.supply) * BigInt(10 ** TOKEN.decimals);
await mintV1(umi, {
  mint: mint.publicKey,
  authority: umi.identity,
  tokenOwner: wallet.publicKey, // ATA выводится автоматически
  amount,
  tokenStandard: TokenStandard.Fungible,
}).sendAndConfirm(umi);
console.log("   эмиссия зачислена на твой кошелёк");

// --- 5. Отзыв прав (фиксированная эмиссия / без заморозки) -----------------
if (TOKEN.revokeMintAuthority) {
  step("Отзываю mint authority (эмиссия больше не увеличится)...");
  await setAuthority(umi, {
    owned: mint.publicKey,
    owner: umi.identity,
    authorityType: AuthorityType.MintTokens,
    newAuthority: none(),
  }).sendAndConfirm(umi);
}
if (TOKEN.revokeFreezeAuthority) {
  step("Отзываю freeze authority (нельзя замораживать кошельки)...");
  await setAuthority(umi, {
    owned: mint.publicKey,
    owner: umi.identity,
    authorityType: AuthorityType.FreezeAccount,
    newAuthority: none(),
  }).sendAndConfirm(umi);
}

// --- Готово ----------------------------------------------------------------
const cluster = NETWORK === "mainnet" ? "" : "?cluster=devnet";
console.log("\n🎉 Готово! Токен $RAMIN выпущен.");
console.log(`   Mint:     ${mint.publicKey}`);
console.log(`   Explorer: https://explorer.solana.com/address/${mint.publicKey}${cluster}`);
console.log(`   Solscan:  https://solscan.io/token/${mint.publicKey}${NETWORK === "mainnet" ? "" : "?cluster=devnet"}`);
if (NETWORK === "mainnet") {
  console.log("\nДальше (по желанию): создать пул ликвидности на Raydium/Orca, чтобы токеном можно было торговать.");
}
