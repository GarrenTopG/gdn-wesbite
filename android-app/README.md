# Aurorah CAN Android app

This folder contains a Jetpack Compose Android app screen implementation. It is designed to fit into a new Android Studio project; this website repository does not include the Android Gradle project files. The Home screen is already implemented in `MainActivity.kt` and is kept as-is alongside the other app screens.

## Put the code into Android Studio

1. In Android Studio, create a new **Empty Activity** project:
   - Language: **Kotlin**
   - Build configuration: **Kotlin DSL**
   - Enable **Jetpack Compose**
   - Use a minimum SDK of **26 or higher**
2. In the generated project, open `app/src/main/java/<your package path>/MainActivity.kt`. Replace that file's contents with the complete `android-app/MainActivity.kt` file from this repository.
3. If the generated package differs from `org.aurorahcan.app`, edit the first `package` line in the pasted Kotlin file so it matches your Android Studio project's package. Keep the rest of the file unchanged.
4. Open the **app module** `build.gradle.kts`. Keep the Compose dependencies and Compose BOM that Android Studio generated. Inside the `dependencies { }` block, add:

   ```kotlin
   implementation("androidx.compose.material:material-icons-extended")
   implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
   implementation("io.coil-kt:coil-compose:2.7.0")
   ```

   Click **Sync Now** and wait for Gradle sync to finish.
5. Open `app/src/main/AndroidManifest.xml`. Add the Internet permission directly under the opening `<manifest>` tag, before `<application>`:

   ```xml
   <uses-permission android:name="android.permission.INTERNET" />
   ```

   Add `android:launchMode="singleTop"` to the activity and add this verified
   HTTPS app-link filter to its existing `<activity>` element. Keep any existing
   launcher filter:

   ```xml
   <intent-filter android:autoVerify="true">
       <action android:name="android.intent.action.VIEW" />
       <category android:name="android.intent.category.DEFAULT" />
       <category android:name="android.intent.category.BROWSABLE" />
       <data
           android:scheme="https"
           android:host="aurorah-web-hub.onrender.com"
           android:path="/mobile-auth/callback" />
   </intent-filter>
   ```

   The website must serve `/.well-known/assetlinks.json` with the Android
   application ID and the SHA-256 fingerprint of the signing certificate used
   for the build. Android Studio's debug certificate and the Play Store release
   certificate have different fingerprints; publish both if both builds should
   open the app link. Do not replace the verified HTTPS app link with a custom
   URL scheme.

6. Start an emulator or connect an Android device, then click **Run**. The app calls the live site at `https://aurorah-web-hub.onrender.com`.

### Test against a local backend

For the Android emulator, set `SITE_BASE_URL` near the top of `MainActivity.kt` to `http://10.0.2.2:8000`. In `AndroidManifest.xml`, temporarily add `android:usesCleartextTraffic="true"` to the `<application>` element when using local HTTP. Remove that setting before release; production traffic should use HTTPS. A physical phone needs to use the development computer's reachable LAN address instead of `10.0.2.2`.

The local backend must be running and include this repository's mobile API routes. Deploy the updated backend before using the live site. Network submissions and profile actions require the mobile API to be available.

## Screens and navigation

- **Home**: existing action-led dashboard, latest story, community needs, and location/contact information.
- **Get Help**: eligibility, emergency notice, privacy context, and a three-step assistance request form.
- **Get Involved**: community needs feed, offer-to-help flow, donation pledge flow, and volunteer roles/application.
- **Stories**: category-filtered public news feed with article images, full article detail, and a link to the website article.
- **Profile**: sign-in/register, editable name and phone, contact preference, sign-out, and links to About, Contact, and Privacy.

Profile sign-in supports email/password plus Google and Microsoft. Provider
authentication opens in the system browser and returns through the verified
`https://aurorah-web-hub.onrender.com/mobile-auth/callback` app link. The app creates a
PKCE verifier before starting, exchanges the one-use callback code with the
backend, and only then stores the mobile bearer token in memory. Configure
Google/Microsoft server credentials and callback URLs as described in the root
README; the buttons appear only when the server reports those providers as
configured. If a provider email matches an existing password account, sign in
to that website account and explicitly connect the provider from the website
account menu before using that identity in the mobile app.

The bottom navigation labels remain visible with their icons. Browsing stories and learning about Aurorah CAN do not require an account; sign-in is requested only when submitting a task that requires it.

## API limits and behavior

- Home, Stories, and current community needs use the public `/api/news` and `/api/needs` feeds. Need cards display the optional `imageUrl` and `imageAlt` from the community-need record; staff must provide an image URL in the website admin for the actual image to appear. Missing or unavailable images use a neutral placeholder. News responses include the article `summary`, full `content`, and optional `image_url`, which the app loads over HTTPS. There is no separate mobile article-detail endpoint.
- Assistance requests, volunteer applications, donation pledges, and offers to help require sign-in and are submitted to the existing mobile API.
- A donation is a pledge only: the app does not process payments. The mobile API does not collect Section 18A tax-receipt information, so the app links to the website for that flow.
- The API does not expose request, donation, or volunteer submission history/status. The app does not show tracking or application-history features.
- The sample keeps the bearer token in memory only. Signing out clears it on the device and asks the API to revoke the session. If the network is unavailable, the app reports that the server-side token may remain valid until expiry. Reopening the app requires signing in again. Secure token storage should be added only as part of a reviewed production authentication lifecycle.
