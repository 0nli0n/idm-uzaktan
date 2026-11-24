# IDM Uzaktan

Bilgisayardaki Internet Download Manager'ı (IDM) Android telefondan ev Wi-Fi'ı üzerinden yönetmenizi sağlar.

```
Telefon (IDM Uzaktan uygulaması)  ──Wi-Fi──>  Bilgisayar (köprü sunucusu)  ──>  IDM
```

## Neler yapabilirsiniz

- Telefondan link gönderip IDM'de **hemen indirmeyi başlatmak** ya da **kuyruğa eklemek**
- Herhangi bir uygulamada (Chrome, Telegram, YouTube…) **Paylaş → "IDM Uzaktan"** ile linki doğrudan bilgisayara göndermek
- Kayıt klasörünü ve dosya adını seçmek
- IDM indirme listesini, ilerlemeyi ve hızı görmek (2–5 saniyede bir yenilenir)
- Tek bir indirmeyi **duraklatmak / devam ettirmek**, **tümünü durdurmak**, **kuyruğu başlatmak / durdurmak**
- IDM kapalıysa uzaktan açmak
- Bilgisayardaki indirme klasörlerinde gezinmek ve dosyaları **telefona indirmek**
- Bir dosyanın klasörünü bilgisayarda açmak

---

## 1. Bilgisayar kurulumu (bir kez)

1. **Python 3'ü kurun:** https://www.python.org/downloads/
   Kurulumun ilk ekranında **"Add python.exe to PATH"** kutusunu işaretleyin.
2. `pc-sunucu` klasörünü kalıcı bir yere kopyalayın (ör. `C:\IDM Uzaktan`).
3. **`guvenlik_duvari_izni.bat`** dosyasına çift tıklayın ve yönetici iznini onaylayın. Bu adım telefonun bilgisayara ulaşabilmesi için gerekli.
   Wi-Fi ağınızın Windows'ta **"Özel ağ"** olarak ayarlı olması gerekiyor: *Ayarlar → Ağ ve İnternet → Wi-Fi → ağın adı → Ağ profili türü: Özel*
4. **`baslat.bat`** dosyasına çift tıklayın. Açılan pencerede bilgisayarın **adresi** ve 6 haneli **PIN** görünür. Pencere açık kaldığı sürece sunucu çalışır.

**İsteğe bağlı:** `otomatik_baslat_ac_kapat.bat` dosyasını çalıştırırsanız sunucu Windows açılışında arka planda, pencere açmadan başlar. Bu durumda PIN'i `config.json` dosyasında görebilirsiniz. Dosyayı tekrar çalıştırmak otomatik başlatmayı kapatır.

## 2. APK'yı oluşturma

İki yoldan birini seçin.

### A) Android Studio ile (bilgisayarda)
1. Android Studio'yu kurun: https://developer.android.com/studio
2. **Open** deyip `android` klasörünü seçin. İlk açılışta Gradle gerekli dosyaları indirir; bu birkaç dakika sürebilir.
3. Menüden **Build → Build App Bundle(s) / APK(s) → Build APK(s)** seçin.
4. APK şurada oluşur: `android/app/build/outputs/apk/debug/app-debug.apk`

### B) GitHub ile (Android Studio kurmadan)
1. GitHub'da yeni bir **özel (private)** depo oluşturun ve bu klasörün **tamamını** yükleyin. Gizli `.github` klasörü de yüklenmeli; bunun için en kolay yol GitHub Desktop.
2. Deponun **Actions** sekmesinde "APK derle" işi kendiliğinden çalışır (yaklaşık 5 dakika).
3. İş bitince sayfanın altındaki **Artifacts** bölümünden `IDM-Uzaktan-apk` dosyasını indirin. Zip'in içinden APK çıkar. Bunu telefondan da yapabilirsiniz.

### Telefona kurma
APK'yı telefona atın (USB, Drive, Telegram vb.) ve açın. Android "bilinmeyen kaynaklardan yükleme" izni isterse verin.

Uygulama, projeyle birlikte gelen sabit bir anahtarla imzalanır. Böylece yeni bir sürümü hangi bilgisayarda derlerseniz derleyin, eskisinin üzerine kurulur.

## 3. Kullanım

1. Bilgisayarda sunucu açıkken uygulamayı açın. Bilgisayar listede otomatik görünür. Görünmezse IP adresini elle girin.
2. Sunucu penceresindeki **PIN**'i girip **Bağlan**'a dokunun. Bağlantı kaydedilir, bir daha sorulmaz.
3. **Yeni indirme** düğmesiyle link ekleyin. **Hemen indir** indirmeyi başlatır; **Kuyruğa ekle** yalnızca listeye ekler, sonra ▶ (Kuyruğu başlat) ile başlatırsınız.
4. Bir indirmeye dokunun: telefona indirme, klasörü açma, linki kopyalama veya paylaşma seçenekleri çıkar.
5. Telefona indirilen dosyalar **İndirilenler/IDM Uzaktan** klasörüne kaydedilir.

## 4. Bilinen sınırlamalar

IDM'in resmi bir uzaktan kontrol arayüzü yok. Uygulama IDM'in komut satırını ve indirme listesini (Windows kayıt defteri) kullanıyor. Bu yüzden:

- **Duraklat / Devam et** IDM'in ana penceresi üzerinden çalışır. Sunucu, IDM listesinde ilgili satırı seçer ve IDM'in kendi "Devam" ya da "Durdur" düğmesine basar. Bunun için IDM'in açık olması gerekir; simge durumunda ya da sistem tepsisinde olması sorun değil. IDM'de soldaki kategorilerden **"Tüm indirmeler"** seçili olmalı. Düğmeler yalnızca adlarıyla bulunur, bu yüzden yanlış bir düğmeye (ör. "Sil") basılamaz. IDM güncellemesi pencereyi değiştirirse bu özellik çalışmayabilir; o zaman tanılama bilgisini gönderin. Sunucu klasöründe `idm_pencere.py` dosyasının da bulunması gerekir.
- **İlerleme ve hız tahminidir.** IDM'in geçici klasöründeki parçaların boyutundan hesaplanır. İlerleme hiç görünmüyorsa IDM'in geçici klasörü farklı bir yerde olabilir. Bu durumda `config.json` içindeki `idm_gecici_klasor` ayarını, IDM → Seçenekler → Kaydetme Yeri'ndeki geçici klasör yoluyla doldurun.
- **"Yeniden indir"** aynı linki IDM'e tekrar gönderir. IDM bunu yeni bir kopya olarak kaydedebilir.
- Uygulama yalnızca **aynı Wi-Fi ağında** çalışır; internet üzerinden erişim kapalıdır.

Liste veya ilerleme yanlış görünürse uygulamada **⋮ → Tanılama bilgisi** metnini kopyalayıp gönderin; sorunu ona göre düzeltebiliriz. Çerez ve parola gibi bilgiler bu metinde gizlenir.

## 5. Sorun giderme

| Sorun | Çözüm |
|---|---|
| Bilgisayar listede çıkmıyor | `guvenlik_duvari_izni.bat` dosyasını çalıştırın, ağın "Özel" olduğunu kontrol edin, IP'yi elle girin |
| "PIN hatalı" | PIN'i sunucu penceresinden veya `config.json` dosyasından kontrol edin. 8 hatalı denemeden sonra 5 dakika beklemeniz gerekir |
| "IDM bulunamadı" | `config.json` içindeki `idm_yolu` ayarına `IDMan.exe` dosyasının tam yolunu yazın |
| Port hatası | Sunucu zaten açık olabilir. Değilse `config.json` içinden `port` ayarını değiştirin ve uygulamada aynı portu girin |
| Dosyalar sekmesi boş | `config.json` içindeki `indirme_klasorleri` listesine klasör yollarını ekleyin, ör. `["D:\\İndirmeler"]` |

## 6. Güvenlik

- Sunucu **yalnızca yerel ağdan** (192.168.x.x gibi) gelen istekleri kabul eder.
- Her istek PIN ile doğrulanır; hatalı denemeler engellenir.
- Bağlantı ev ağında düz HTTP'dir. Herkese açık Wi-Fi ağlarında (kafe, otel) sunucuyu çalıştırmayın.
- Yeni bir PIN almak için `config.json` dosyasındaki `"pin"` değerini silip sunucuyu yeniden başlatın.

## Klasörler

```
pc-sunucu/   Bilgisayar tarafı (Python, ek kurulum gerektirmez)
android/     Android uygulaması (Kotlin + Jetpack Compose)
.github/     GitHub'da otomatik APK derleme
```
