# Şirket Geri Alım Takibi — Mevcut Beyan Takibi Reposuna Ekleme

Bu ek, senin `beyan-takibi` (Pelosi/Trump tracker) reponun **yanına**, ayrı bir modül
olarak eklenmek üzere hazırlandı. Mevcut Python/Telegram/GitHub Actions altyapısını
tekrar kurmuyor — kendi bağımsız script'i ve workflow'u var, sadece aynı repoyu paylaşıyor.

## Ne yapıyor

BIST şirketlerinin **kendi paylarını geri aldığına** dair KAP bildirimlerini (Payların
Geri Alınmasına İlişkin Bildirim) takip eder ve her yeni bildirimde:
- **hangi şirket**, **kaç TL/adet**, **hangi fiyattan**, **ne zaman** aldığını,
- geri alım sonrası **sermayedeki payının** ne olduğunu

çıkarıp `site/kap-buybacks.json` dosyasına yazar ve (varsa) Telegram'a mesaj atar.
Web sayfası `site/kap-buyback.html` bu dosyayı okuyup filtrelenebilir bir tabloda gösterir.

## Kurulum (yaklaşık 5 dakika)

1. Bu zip'in içindeki tüm dosya ve klasörleri **mevcut** `beyan-takibi` reponun köküne
   yükle (mevcut dosyaların üzerine yazmaz, sadece yeni klasör/dosyalar ekler):
   - `tracker/kap_client.py`, `tracker/kap_buyback.py`, `tracker/telegram_notify.py`,
     `tracker/main.py` (bunlar `tracker.kap_*` adıyla, mevcut `tracker/` paketinin
     içine ekleniyor — isim çakışması olursa, örn. senin de bir `main.py`'ın varsa,
     bu dosyayı `tracker/kap_main.py` olarak yükleyip aşağıdaki workflow'da
     `python -m tracker.main` yerine `python -m tracker.kap_main` yaz)
   - `.github/workflows/kap-buyback.yml`
   - `site/kap-buyback.html`
   - `tests/test_kap_buyback.py`
   - `requirements.txt` içeriğini kendi `requirements.txt`'ine ekle (zaten `requests`
     varsa sadece `beautifulsoup4` satırını ekle)

2. **Secrets zaten var** — `SEC_USER_AGENT`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
   önceki kurulumdan mevcut, tekrar eklemene gerek yok. Bu modül aynı secret'ları kullanıyor.

3. Ana sayfana (`site/index.html`) bu yeni sayfaya bir link ekle, örn.:
   ```html
   <a href="kap-buyback.html">Şirket Geri Alımları →</a>
   ```

4. **Actions → kap-buyback-tracker → Run workflow** ile ilk çalıştırmayı elle başlat:
   - `days_back`: `400` yap (geçmişi doldurmak için)
   - `silent`: `true` yap (ilk doldurmada Telegram'ı sel basmasın)

   Site adresi: `https://<kullanıcı-adın>.github.io/<repo-adın>/kap-buyback.html`

5. Sonraki çalıştırmalar otomatik: hafta içi, BIST işlem saatlerinde (10:00-19:00
   İstanbul) saatte bir kontrol eder ve yalnızca **yeni** bildirimlerde Telegram
   mesajı atar.

## Önemli sınırlama — bunu ilk gerçek çalıştırmada kontrol et

Bu modülü geliştirdiğim ortamdan **kap.org.tr'ye canlı ağ erişimi yoktu** (kurumsal
proxy engelledi), o yüzden KAP'ın gerçek bildirim HTML'ini görüp test edemedim.
Parser, GitHub'da bulduğum başka bir KAP-scraper projesinin dokümantasyonundaki API
uç noktalarına (`/tr/api/disclosure/members/byCriteria`,
`/tr/api/notification/attachment-detail/{id}`) ve KAP'ın tipik
"etiket → değer" tablo yapısına göre yazıldı, ama **canlı bir "Payların Geri Alınmasına
İlişkin Bildirim" örneğiyle doğrulanmadı**.

Ne olabilir:
- API endpoint'leri ve alan adları (subject metni) değişmemiş olmalı — bunlar KAP'ın
  arama sayfasının kendisinin kullandığı, stabil uç noktalar.
- Ama tablo içindeki Türkçe etiketler (`İşlem Tarihi`, `İşlem Adedi` vb.) gerçek
  bildirimde biraz farklı yazılmış olabilir. Parser bunu **sessizce yanlış** okumak
  yerine, beklediği alanları bulamazsa satırı `needs_review: true` ile işaretler ve
  ham HTML'i (`raw_fields` içinde) saklar — hiçbir veri sessizce kaybolmaz.

**İlk çalıştırmadan sonra**: `site/kap-buybacks.json` dosyasını aç, birkaç satıra bak.
`needs_review: true` olan satırlarsa `raw_fields` içindeki gerçek etiketleri bana
(veya bir sonraki Claude oturumuna) yapıştır, parser'ı gerçek veriye göre bir dakikada
düzeltirim. GitHub Actions logundaki "X new rows need manual review" satırı da bunu
sana hatırlatacak.

## Dosya yapısı

```
tracker/
  kap_client.py        # KAP JSON API istemcisi (rate-limit, warmup, retry)
  kap_buyback.py        # bildirimleri çekme + HTML tablo ayrıştırma + JSON store
  telegram_notify.py     # Telegram mesaj gönderimi
  main.py                # çalıştırılabilir giriş noktası
site/
  kap-buyback.html        # web sayfası (arama, sıralama, "YENİ" etiketi, mobil uyumlu)
  kap-buybacks.json        # (otomatik üretilir) veri dosyası
.github/workflows/
  kap-buyback.yml           # saatlik otomatik çalıştırma + repoya commit
tests/
  test_kap_buyback.py        # sentetik HTML ile parser testleri (geçiyor)
```
