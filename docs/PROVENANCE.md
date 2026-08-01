# 🔐 Provenance & Commit Signing / إثبات الأسبقية وتوقيع الكوميتات

> الهدف: أن يكون بإمكان أي شخص — أو أي جهة قانونية — أن يتحقق آليًا أن هذا
> المحتوى لي أنا، وأنه نُشر قبل أي نسخة أخرى.

Content fingerprint: `MJDALSK-CANARY-9F4C2E7A1B`
Canonical origin: <https://github.com/majid-alsakani/majid-alsakani>
First published: **2026-01-12** (GitHub-timestamped repository creation)

---

## 1. لماذا التوقيع مهم

| بدون توقيع | مع توقيع Verified |
| --- | --- |
| أي شخص يقدر يضع اسمك في `git config` ويدّعي أنه أنت | التوقيع مرتبط بمفتاح خاص لا يملكه غيرك |
| الكوميت مجرد نص | الكوميت مختوم تشفيريًا + مختوم زمنيًا من GitHub |
| صعب الإثبات القانوني | دليل تقني قابل للتحقق من طرف ثالث |

---

## 2. إعداد التوقيع بـ SSH (الأسهل والأحدث)

```sh
# 1) أنشئ مفتاح توقيع مخصص
ssh-keygen -t ed25519 -C "majidalsakani@gmail.com" -f ~/.ssh/git_signing

# 2) اضبط Git ليستخدمه في التوقيع
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/git_signing.pub
git config --global commit.gpgsign true
git config --global tag.gpgsign true
git config --global user.name  "Majid Al-Sakani"
git config --global user.email "majidalsakani@gmail.com"

# 3) اطبع المفتاح العام وانسخه
cat ~/.ssh/git_signing.pub
```

ثم على GitHub:
**Settings → SSH and GPG keys → New SSH key → Key type: `Signing Key`** → الصق المفتاح.

> ⚠️ مهم: يجب أن يكون `user.email` نفس بريد مُتحقَّق منه في حسابك،
> وإلا ستظهر الكوميتات بعلامة `Unverified`.

---

## 3. البديل: التوقيع بـ GPG

```sh
gpg --full-generate-key            # اختر RSA 4096
gpg --list-secret-keys --keyid-format=long
gpg --armor --export <KEY_ID>      # انسخ الناتج إلى GitHub → New GPG key

git config --global user.signingkey <KEY_ID>
git config --global commit.gpgsign true
```

---

## 4. إجبار كل الكوميتات المستقبلية على أن تكون موثّقة

- فعّل **Vigilant mode**: `Settings → SSH and GPG keys → Flag unsigned commits as unverified`.
  بعدها أي كوميت غير موقّع باسمك يظهر صراحةً كـ **Unverified** — أي انتحال يُكشف فورًا.
- الكوميتات التي تُنشأ من واجهة GitHub أو من GitHub Actions تُوقَّع تلقائيًا بمفتاح GitHub.
- احمِ الفرع: `Settings → Branches → Protect main → Require signed commits`.

---

## 5. خطة التحقق (Verification Plan)

أي شخص يريد التأكد أن المحتوى لي:

```sh
git clone https://github.com/majid-alsakani/majid-alsakani.git
cd majid-alsakani

# 1) تحقق من تواقيع الكوميتات
git log --show-signature -5

# 2) اعرض أول ظهور للمحتوى تاريخيًا
git log --reverse --format="%H %ad %an %s" --date=iso -- README.md | head -1

# 3) اعرض تاريخ أي سطر بعينه (يكشف من كتبه أولًا)
git log -S "Backend Engineer · API Architect" --format="%ad %an" --date=iso -- README.md

# 4) تحقق من وجود البصمة المخفية
grep -c "MJDALSK-CANARY-9F4C2E7A1B" README.md COPYRIGHT.md NOTICE LICENSE
```

**نتيجة التحقق المتوقعة:** أقدم ظهور للمحتوى موجود في هذا المستودع بختم زمني
من GitHub، وأي مستودع آخر يحمل نفس النص سيكون تاريخه لاحقًا بالضرورة.

---

## 6. ختم زمني خارجي (طبقة إضافية اختيارية)

لتقوية الإثبات أمام جهة خارجية لا تثق بـ GitHub وحدها:

```sh
# بصمة تشفيرية للمحتوى الحالي
sha256sum README.md LICENSE COPYRIGHT.md NOTICE > CONTENT.sha256

# انشرها في مكان ذي ختم زمني مستقل (مثال: OpenTimestamps)
# ots stamp CONTENT.sha256
```

احتفظ بـ `CONTENT.sha256` وملف `.ots` الناتج خارج المستودع كنسخة احتياطية.

---

## 7. الطبقات الخمس مجتمعة

```text
  ①  LICENSE (CC BY-NC-ND 4.0)  ─── الحق القانوني
  ②  COPYRIGHT.md + NOTICE      ─── إعلان الملكية والبريد
  ③  CITATION.cff               ─── النسبة الأكاديمية/الآلية
  ④  Canaries + fingerprints    ─── كشف النسخ تقنيًا
  ⑤  Signed commits + timestamps ── إثبات الأسبقية
```

<sub>© 2026 Majid Al-Sakani — <https://github.com/majid-alsakani></sub>
