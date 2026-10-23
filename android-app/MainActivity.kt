package org.aurorahcan.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Article
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.SupportAgent
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImagePainter
import coil.compose.SubcomposeAsyncImage
import coil.compose.SubcomposeAsyncImageContent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

private const val SITE_BASE_URL = "https://aurorahcan.org.za"
private const val ORG_ADDRESS = "27 Lovebird Walk, Sunbird Park, Cape Town, 7580"
private val Brand = Color(0xFF752D42)
private val BrandMid = Color(0xFF943D56)
private val BrandPale = Color(0xFFFDF2F8)
private val Page = Color(0xFFFAF8F9)
private val Ink = Color(0xFF28252A)
private val Muted = Color(0xFF625D62)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(
                colorScheme = lightColorScheme(
                    primary = Brand,
                    onPrimary = Color.White,
                    secondary = BrandMid,
                    background = Page,
                    surface = Color.White,
                    onSurface = Ink
                )
            ) {
                AurorahApp()
            }
        }
    }
}

private data class AppTab(val label: String, val icon: ImageVector)
private val tabs = listOf(
    AppTab("Home", Icons.Filled.Home),
    AppTab("Get Help", Icons.Filled.SupportAgent),
    AppTab("Get Involved", Icons.Filled.FavoriteBorder),
    AppTab("Stories", Icons.Filled.Article),
    AppTab("Profile", Icons.Filled.Person)
)

private data class AppUser(
    val id: Int,
    val fullName: String,
    val email: String,
    val role: String,
    val token: String,
    val phone: String = "",
    val preferredContact: String = "Email"
)

private data class Story(
    val id: Int,
    val title: String,
    val summary: String,
    val category: String,
    val timestamp: String,
    val imageUrl: String? = null
)

private data class CommunityNeed(
    val id: Int,
    val title: String,
    val description: String,
    val location: String,
    val priority: String,
    val category: String
)

private fun resolveImageUrl(imageUrl: String?): String? {
    val candidate = imageUrl?.trim()?.takeIf { it.isNotEmpty() && it != "null" } ?: return null
    return when {
        candidate.startsWith("//") -> "https:$candidate"
        candidate.startsWith("/", ignoreCase = false) -> "$SITE_BASE_URL$candidate"
        candidate.startsWith("http://", ignoreCase = true) ->
            "https://${candidate.substringAfter("://")}"
        candidate.startsWith("https://", ignoreCase = true) -> candidate
        else -> "$SITE_BASE_URL/${candidate.trimStart('/')}"
    }
}

@Composable
private fun AurorahApp() {
    var selectedTab by rememberSaveable { mutableStateOf(0) }
    var user by remember { mutableStateOf<AppUser?>(null) }
    val context = LocalContext.current
    val openWebsite: (String) -> Unit = { path ->
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("$SITE_BASE_URL$path")))
    }

    Scaffold(
        containerColor = Page,
        bottomBar = {
            NavigationBar(containerColor = Color.White) {
                tabs.forEachIndexed { index, tab ->
                    NavigationBarItem(
                        selected = selectedTab == index,
                        onClick = { selectedTab = index },
                        icon = { Icon(tab.icon, contentDescription = null) },
                        label = { Text(tab.label, fontSize = 10.sp, maxLines = 1) }
                    )
                }
            }
        }
    ) { padding ->
        when (selectedTab) {
            0 -> HomeScreen(
                modifier = Modifier.padding(padding),
                onSelectTab = { selectedTab = it },
                onOpenWebsite = openWebsite
            )
            1 -> HelpScreen(
                modifier = Modifier.padding(padding),
                user = user,
                onSignIn = { selectedTab = 4 },
                onOpenWebsite = openWebsite
            )
            2 -> InvolvedScreen(
                modifier = Modifier.padding(padding),
                user = user,
                onSignIn = { selectedTab = 4 },
                onOpenWebsite = openWebsite
            )
            3 -> StoriesScreen(
                modifier = Modifier.padding(padding),
                onOpenWebsite = openWebsite
            )
            else -> ProfileScreen(
                modifier = Modifier.padding(padding),
                user = user,
                onUserChanged = { user = it },
                onOpenWebsite = openWebsite
            )
        }
    }
}

@Composable
private fun HomeScreen(
    modifier: Modifier,
    onSelectTab: (Int) -> Unit,
    onOpenWebsite: (String) -> Unit
) {
    var stories by remember { mutableStateOf<List<Story>>(emptyList()) }
    var needs by remember { mutableStateOf<List<CommunityNeed>>(emptyList()) }
    var newsError by remember { mutableStateOf<String?>(null) }
    var needsError by remember { mutableStateOf<String?>(null) }
    var refreshKey by rememberSaveable { mutableStateOf(0) }
    var loading by remember { mutableStateOf(true) }

    LaunchedEffect(refreshKey) {
        loading = true
        val response = withContext(Dispatchers.IO) { Api.homeFeeds() }
        stories = response.first
        needs = response.second
        newsError = response.third
        needsError = response.fourth
        loading = false
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .background(Page)
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(Brush.linearGradient(listOf(Brand, BrandMid)), RoundedCornerShape(22.dp))
                .padding(22.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Text("AURORAH NPC  ·  KUILS RIVER, CAPE TOWN", color = Color(0xFFFCE7F3), fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
            Text("Practical community support, rooted in Kuils River.", color = Color.White, fontSize = 27.sp, lineHeight = 33.sp, fontWeight = FontWeight.ExtraBold)
            Text(
                "Supporting vulnerable households and young people in Kuils River, Sunbird Park, and nearby Cape Flats communities.",
                color = Color.White.copy(alpha = 0.92f),
                fontSize = 15.sp,
                lineHeight = 22.sp
            )
            Button(
                onClick = { onSelectTab(1) },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = Color.White, contentColor = Brand)
            ) { Text("Get Help  →", fontWeight = FontWeight.Bold) }
            OutlinedButton(
                onClick = { onSelectTab(2) },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White)
            ) { Text("Get Involved  ♥", fontWeight = FontWeight.Bold) }
        }
        Notice("A community network, not a government service.", BrandPale, Brand)

        SectionTitle("Ways to help nearby")
        when {
            needs.isNotEmpty() -> needs.take(2).forEach { need ->
                NeedCard(need, onClick = { onSelectTab(2) })
            }
            loading -> BodyText("Loading current community needs…")
            needsError != null -> RetryRow("Community needs could not be loaded.") { refreshKey++ }
            else -> BodyText("Explore current community needs, donation pledges, or volunteering.")
        }

        SectionTitle("Latest story")
        when {
            stories.isNotEmpty() -> StoryCard(stories.first()) { onSelectTab(3) }
            loading -> BodyText("Loading community updates…")
            newsError != null -> RetryRow("The latest story could not be loaded.") { refreshKey++ }
            else -> StoryCard(
                Story(0, "A place for young readers in Sunbird Park",
                    "Aurorah CAN established a community mini-library in July 2022 as part of Nelson Mandela Day.",
                    "Community milestone", ""),
                onClick = { onOpenWebsite("/news") }
            )
        }

        Card(colors = CardDefaults.cardColors(containerColor = Brand), shape = RoundedCornerShape(18.dp)) {
            Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Find us", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
                    Icon(Icons.Filled.LocationOn, contentDescription = null, tint = Color(0xFFFCE7F3))
                    Text(ORG_ADDRESS, color = Color.White, fontSize = 14.sp, lineHeight = 20.sp)
                }
                Text("Mon–Fri 08:00–17:00; Sat 09:00–14:00", color = Color.White, fontSize = 14.sp)
                TextButton(onClick = { onOpenWebsite("/about") }) {
                    Text("About Aurorah CAN  →", color = Color.White, fontWeight = FontWeight.Bold)
                }
            }
        }
        Spacer(Modifier.height(8.dp))
    }
}

@Composable
private fun HelpScreen(
    modifier: Modifier,
    user: AppUser?,
    onSignIn: () -> Unit,
    onOpenWebsite: (String) -> Unit
) {
    var category by rememberSaveable { mutableStateOf("Food Parcel") }
    var phone by rememberSaveable { mutableStateOf("") }
    var area by rememberSaveable { mutableStateOf("") }
    var details by rememberSaveable { mutableStateOf("") }
    var urgency by rememberSaveable { mutableStateOf("Medium") }
    var privacyAccepted by rememberSaveable { mutableStateOf(false) }
    var step by rememberSaveable { mutableStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var success by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    FormPage(modifier, "Get Help") {
        BodyText("Aurorah CAN considers requests from Kuils River, Sunbird Park, and nearby Cape Flats communities. Requests are reviewed individually; assistance depends on eligibility and available resources.")
        Notice("Not an emergency service. If you are in immediate danger or need urgent medical help, call 112 from a mobile phone. For a police emergency, call 10111.", Color(0xFFFFF6E5), Color(0xFF7A4B00))
        BodyText("We use the information you provide to assess your request and contact you. Share only details needed for review. Your request is not published as a story.")
        if (user == null) {
            SignInPrompt("Sign in or create an account to submit an assistance request.", onSignIn)
        } else if (success != null) {
            Notice(success!!, Color(0xFFEAF7ED), Color(0xFF176B35))
            BodyText("Submitting a request does not guarantee assistance. The team reviews requests based on need and available resources.")
        } else {
            Text("Step ${step + 1} of 3", color = Brand, fontWeight = FontWeight.Bold)
            when (step) {
                0 -> {
                    SectionTitle("What support do you need?")
                    ChoiceChips("Type of support", listOf("Food Parcel", "Financial Aid", "Medical Assistance", "Educational Support", "Employment Help", "Housing", "Other"), category) { category = it }
                    ChoiceChips("Urgency", listOf("Medium", "High", "Critical"), urgency) { urgency = it }
                    InputField("Suburb or area", area, { area = it }, required = true)
                }
                1 -> {
                    SectionTitle("How can we contact you?")
                    InputField("Contact phone", phone, { phone = it }, keyboardType = KeyboardType.Phone, required = true)
                    InputField("Briefly describe what support you need", details, { details = it }, required = true, minLines = 4)
                    Row(verticalAlignment = Alignment.Top) {
                        Checkbox(checked = privacyAccepted, onCheckedChange = { privacyAccepted = it })
                        BodyText("I agree Aurorah NPC may use these details to assess this request and contact me.")
                    }
                }
                else -> {
                    SectionTitle("Review your request")
                    BodyText("Support: $category")
                    BodyText("Urgency: $urgency")
                    BodyText("Area: $area")
                    BodyText("Contact phone: $phone")
                    BodyText("Request details: $details")
                    Notice("Your request will be reviewed based on eligibility and available resources. Submitting it does not guarantee assistance.", Color(0xFFFFF6E5), Color(0xFF7A4B00))
                }
            }
            error?.let { ErrorNotice(it) }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (step > 0) {
                    OutlinedButton(
                        onClick = { error = null; step-- },
                        modifier = Modifier.weight(1f)
                    ) { Text("Back") }
                }
                PrimaryButton(
                    if (step < 2) "Continue" else "Submit request",
                    busy,
                    Modifier.weight(1f)
                ) {
                    error = when (step) {
                        0 -> if (area.isBlank()) "Enter your suburb or area." else null
                        1 -> validate(area, phone, details, privacyAccepted)
                        else -> null
                    }
                    if (error == null && step < 2) {
                        step++
                    } else if (error == null) {
                        busy = true
                        scope.launch {
                            try {
                                val result = withContext(Dispatchers.IO) {
                                    Api.post("/api/assistance-requests", JSONObject()
                                        .put("location", area.trim())
                                        .put("contactPhone", phone.trim())
                                        .put("category", category)
                                        .put("urgency", urgency)
                                        .put("description", details.trim()), user.token)
                                }
                                success = result.optString("message", "Your request has been submitted for review.")
                            } catch (e: IOException) {
                                error = e.message ?: "The request could not be submitted."
                            } catch (e: JSONException) {
                                error = e.message ?: "The server returned an invalid response."
                            } finally { busy = false }
                        }
                    }
                }
            }
        }
        LinkButton("Read privacy information") { onOpenWebsite("/about#privacy-notice") }
    }
}

@Composable
private fun InvolvedScreen(
    modifier: Modifier,
    user: AppUser?,
    onSignIn: () -> Unit,
    onOpenWebsite: (String) -> Unit
) {
    var destination by rememberSaveable { mutableStateOf("hub") }
    var needs by remember { mutableStateOf<List<CommunityNeed>>(emptyList()) }
    var loadingNeeds by remember { mutableStateOf(false) }
    var needsError by remember { mutableStateOf<String?>(null) }
    var selectedNeed by remember { mutableStateOf<CommunityNeed?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(destination) {
        if (destination == "hub") {
            loadingNeeds = true
            try {
                needs = withContext(Dispatchers.IO) { Api.needs() }
                needsError = null
            } catch (e: IOException) {
                needsError = e.message ?: "Current needs could not be loaded."
            } catch (e: JSONException) {
                needsError = e.message ?: "The community-needs response was invalid."
            } finally { loadingNeeds = false }
        }
    }

    when (destination) {
        "donate" -> DonationScreen(modifier, user, onSignIn, onBack = { destination = "hub" }, onOpenWebsite = onOpenWebsite)
        "volunteer" -> VolunteerScreen(modifier, user, onSignIn, onBack = { destination = "hub" })
        "offer" -> selectedNeed?.let { need ->
            OfferHelpScreen(modifier, user, need, onSignIn) { destination = "hub" }
        }
        else -> FormPage(modifier, "Get Involved") {
            BodyText("Choose a practical way to support community work in Kuils River and nearby communities.")
            HubAction("Donate", "Record a monetary pledge or offer goods. No payment is processed in the app.") { destination = "donate" }
            HubAction("Volunteer", "Explore local roles, safeguarding expectations, and submit your skills and availability.") { destination = "volunteer" }
            SectionTitle("Current ways to help")
            when {
                loadingNeeds -> BodyText("Loading community needs…")
                needsError != null -> ErrorNotice(needsError!!)
                needs.isEmpty() -> BodyText("There are no current community needs listed. Check back later.")
                else -> needs.forEach { need ->
                    NeedCard(need) {
                        selectedNeed = need
                        destination = "offer"
                    }
                }
            }
        }
    }
}

@Composable
private fun DonationScreen(
    modifier: Modifier,
    user: AppUser?,
    onSignIn: () -> Unit,
    onBack: () -> Unit,
    onOpenWebsite: (String) -> Unit
) {
    var donationType by rememberSaveable { mutableStateOf("monetary") }
    var amount by rememberSaveable { mutableStateOf("") }
    var itemCategory by rememberSaveable { mutableStateOf("Non-Perishable Food / Canned Goods") }
    var itemDescription by rememberSaveable { mutableStateOf("") }
    var logistics by rememberSaveable { mutableStateOf("dropoff") }
    var pickupAddress by rememberSaveable { mutableStateOf("") }
    var step by rememberSaveable { mutableStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var confirmation by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    FormPage(modifier, "Donation pledge") {
        TextButton(onClick = onBack) { Text("← Back to Get Involved", color = Brand) }
        Notice("This records a pledge only. The app does not process payments and this confirmation is not a tax receipt.", Color(0xFFFFF6E5), Color(0xFF7A4B00))
        if (user == null) {
            SignInPrompt("Sign in or register to record a donation pledge.", onSignIn)
        } else if (confirmation != null) {
            Notice(confirmation!!, Color(0xFFEAF7ED), Color(0xFF176B35))
            BodyText("No payment was taken. This is a pledge record only.")
            PrimaryButton("Make another pledge", false) {
                confirmation = null
                step = 0
                amount = ""
                itemDescription = ""
            }
        } else {
            Text("Step ${step + 1} of 3", color = Brand, fontWeight = FontWeight.Bold)
            when (step) {
                0 -> {
                    ChoiceChips("Contribution type", listOf("Monetary", "In-kind goods"), if (donationType == "monetary") "Monetary" else "In-kind goods") {
                        donationType = if (it == "Monetary") "monetary" else "inkind"
                    }
                    if (donationType == "monetary") {
                        ChoiceChips("Suggested amount", listOf("R50", "R200", "R500", "R1000", "Custom"), "Custom") { selected ->
                            amount = selected.removePrefix("R").takeUnless { selected == "Custom" }.orEmpty()
                        }
                        InputField("Amount (ZAR)", amount, { amount = it }, keyboardType = KeyboardType.Decimal, required = true)
                        BodyText("Your pledge will be recorded as an intended contribution. No online payment will be taken.")
                    } else {
                        ChoiceChips("Item category", listOf("Non-Perishable Food / Canned Goods", "Clothing & Footwear", "Blankets & Bedding", "School Supplies & Books", "Other Physical Goods"), itemCategory) { itemCategory = it }
                        InputField("Items and estimated quantities", itemDescription, { itemDescription = it }, required = true, minLines = 3)
                        ChoiceChips("Fulfillment", listOf("I will drop off", "Request collection"), if (logistics == "dropoff") "I will drop off" else "Request collection") {
                            logistics = if (it.startsWith("I will")) "dropoff" else "pickup"
                        }
                        if (logistics == "dropoff") {
                            Notice("Drop off at $ORG_ADDRESS. Mon–Fri 08:00–17:00; Sat 09:00–14:00.", BrandPale, Brand)
                        } else {
                            InputField("Collection address", pickupAddress, { pickupAddress = it }, required = true)
                        }
                    }
                }
                1 -> {
                    SectionTitle("Your account details")
                    BodyText("This pledge is linked to ${user.fullName} (${user.email}). We use account details to record the offer and contact you if needed.")
                    BodyText("For a Section 18A tax receipt request, use the donation form on the website. The mobile API does not currently collect tax receipt details.")
                    LinkButton("Open website donation form") { onOpenWebsite("/donate") }
                }
                else -> {
                    SectionTitle("Review your pledge")
                    BodyText(if (donationType == "monetary") "Monetary pledge: R${amount.trim()}" else "In-kind offer: $itemCategory — $itemDescription")
                    if (donationType == "inkind") BodyText(if (logistics == "dropoff") "You will drop items off at $ORG_ADDRESS." else "Collection address: $pickupAddress")
                    Notice("No payment is processed by this app.", Color(0xFFFFF6E5), Color(0xFF7A4B00))
                }
            }
            error?.let { ErrorNotice(it) }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (step > 0) OutlinedButton(onClick = { error = null; step-- }, modifier = Modifier.weight(1f)) { Text("Back") }
                PrimaryButton(if (step < 2) "Continue" else "Record pledge", busy, Modifier.weight(1f)) {
                    error = when {
                        step == 0 && donationType == "monetary" && (amount.toBigDecimalOrNull() == null || amount.toBigDecimalOrNull()!! < java.math.BigDecimal.TEN) -> "Enter a pledge amount of at least R10."
                        step == 0 && donationType == "inkind" && itemDescription.isBlank() -> "Describe the items you are offering."
                        step == 0 && donationType == "inkind" && logistics == "pickup" && pickupAddress.isBlank() -> "Enter a collection address."
                        else -> null
                    }
                    if (error == null && step < 2) step++ else if (error == null) {
                        busy = true
                        scope.launch {
                            try {
                                val payload = JSONObject()
                                    .put("donationType", donationType)
                                    .put("userEmail", user.email)
                                if (donationType == "monetary") {
                                    payload.put("amount", amount.trim())
                                        .put("category", "General Fund (Where Most Needed)")
                                } else {
                                    payload.put("itemCategory", itemCategory)
                                        .put("itemDescription", itemDescription.trim())
                                        .put("logisticsType", logistics)
                                    if (logistics == "pickup") payload.put("pickupAddress", pickupAddress.trim())
                                }
                                val result = withContext(Dispatchers.IO) { Api.post("/api/donations", payload, user.token) }
                                confirmation = "${result.optString("message", "Your pledge has been recorded.")} Reference: ${result.optString("transactionRef")}"
                            } catch (e: IOException) { error = e.message ?: "The pledge could not be recorded." }
                            catch (e: JSONException) { error = e.message ?: "The server returned an invalid response." }
                            finally { busy = false }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun VolunteerScreen(modifier: Modifier, user: AppUser?, onSignIn: () -> Unit, onBack: () -> Unit) {
    var showForm by rememberSaveable { mutableStateOf(false) }
    var phone by rememberSaveable { mutableStateOf("") }
    var location by rememberSaveable { mutableStateOf("") }
    var skills by rememberSaveable { mutableStateOf("") }
    var availability by rememberSaveable { mutableStateOf("") }
    var privacyAccepted by rememberSaveable { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var success by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    FormPage(modifier, "Volunteer") {
        TextButton(onClick = onBack) { Text("← Back to Get Involved", color = Brand) }
        BodyText("Contribute time and skills to local community work. Roles and availability may vary.")
        InfoCard("Community library assistant", "Support the Sunbird Park mini-library; an example commitment is around four hours a week.")
        InfoCard("Food distribution and logistics", "Help sort and pack food parcels; weekend shifts are one example.")
        InfoCard("Events and fundraising", "Support planning and logistics for local community engagement activities.")
        Notice("Applications are reviewed before placement. Candidates may be invited to interview and orientation. Roles involving children require applicable child-protection checks; additional screening may apply.", Color(0xFFFFF6E5), Color(0xFF7A4B00))
        if (user == null) {
            SignInPrompt("Sign in or register to submit a volunteer application.", onSignIn)
        } else if (success) {
            Notice("Your volunteer application has been received. Applying does not guarantee placement; opportunities depend on suitability, interview, and any role-specific screening.", Color(0xFFEAF7ED), Color(0xFF176B35))
        } else if (!showForm) {
            PrimaryButton("Continue to application", false) { showForm = true }
        } else {
            SectionTitle("Your skills and availability")
            InputField("Phone number", phone, { phone = it }, keyboardType = KeyboardType.Phone, required = true)
            InputField("Suburb or area", location, { location = it }, required = true)
            InputField("Skills and experience", skills, { skills = it }, required = true, minLines = 3)
            InputField("Days and times you are available", availability, { availability = it }, required = true, hint = "For example: Saturday mornings, Monday and Wednesday")
            Row(verticalAlignment = Alignment.Top) {
                Checkbox(checked = privacyAccepted, onCheckedChange = { privacyAccepted = it })
                BodyText("I agree Aurorah NPC may use these details to review my application and contact me.")
            }
            error?.let { ErrorNotice(it) }
            PrimaryButton("Submit volunteer application", busy) {
                error = validate(phone, location, skills, privacyAccepted)
                if (error == null && availability.isBlank()) error = "Please add your availability."
                if (error == null) {
                    busy = true
                    scope.launch {
                        try {
                            Api.post("/api/volunteers", JSONObject()
                                .put("fullName", user.fullName)
                                .put("phone", phone.trim())
                                .put("location", location.trim())
                                .put("skills", skills.trim())
                                .put("availability", availability.trim()), user.token)
                            success = true
                        } catch (e: IOException) { error = e.message ?: "The application could not be submitted." }
                        catch (e: JSONException) { error = e.message ?: "The server returned an invalid response." }
                        finally { busy = false }
                    }
                }
            }
        }
    }
}

@Composable
private fun OfferHelpScreen(modifier: Modifier, user: AppUser?, need: CommunityNeed, onSignIn: () -> Unit, onBack: () -> Unit) {
    var skill by rememberSaveable { mutableStateOf("") }
    var notes by rememberSaveable { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var success by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    FormPage(modifier, "Offer to help") {
        TextButton(onClick = onBack) { Text("← Back to needs", color = Brand) }
        SectionTitle(need.title)
        BodyText(need.description)
        if (user == null) SignInPrompt("Sign in to offer help with this community need.", onSignIn)
        else if (success) Notice("Your offer to help has been submitted.", Color(0xFFEAF7ED), Color(0xFF176B35))
        else {
            InputField("Your skill or how you can help", skill, { skill = it }, required = true, minLines = 2)
            InputField("Additional notes (optional)", notes, { notes = it }, minLines = 3)
            error?.let { ErrorNotice(it) }
            PrimaryButton("Submit offer", busy) {
                error = if (skill.isBlank()) "Describe how you can help." else null
                if (error == null) {
                    busy = true
                    scope.launch {
                        try {
                            Api.post("/api/needs/offer-assistance", JSONObject()
                                .put("needId", need.id)
                                .put("userEmail", user.email)
                                .put("volunteerSkill", skill.trim())
                                .put("notes", notes.trim()), user.token)
                            success = true
                        } catch (e: IOException) { error = e.message ?: "Your offer could not be submitted." }
                        catch (e: JSONException) { error = e.message ?: "The server returned an invalid response." }
                        finally { busy = false }
                    }
                }
            }
        }
    }
}

@Composable
private fun StoriesScreen(modifier: Modifier, onOpenWebsite: (String) -> Unit) {
    var stories by remember { mutableStateOf<List<Story>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshKey by rememberSaveable { mutableStateOf(0) }
    var selectedStory by remember { mutableStateOf<Story?>(null) }
    var category by rememberSaveable { mutableStateOf("All") }
    LaunchedEffect(refreshKey) {
        loading = true
        try {
            stories = withContext(Dispatchers.IO) { Api.stories() }
            error = null
        } catch (e: IOException) {
            error = e.message ?: "Stories could not be loaded."
        } catch (e: JSONException) {
            error = e.message ?: "The stories response was invalid."
        } finally { loading = false }
    }
    val categories = listOf("All") + stories.map { it.category }.filter { it.isNotBlank() }.distinct().sorted()
    FormPage(modifier, if (selectedStory == null) "Stories" else "Story") {
        if (selectedStory != null) {
            TextButton(onClick = { selectedStory = null }) { Text("← All stories", color = Brand) }
            SectionTitle(selectedStory!!.title)
            BodyText(listOf(selectedStory!!.category, selectedStory!!.timestamp.take(10)).filter { it.isNotBlank() }.joinToString(" · "))
            StoryImage(
                selectedStory!!,
                Modifier.fillMaxWidth().height(220.dp)
            )
            BodyText(selectedStory!!.summary)
            Notice("This app feed provides a short summary. Open the website for the full article.", BrandPale, Brand)
            PrimaryButton("Open full story on website", false) { onOpenWebsite("/news") }
        } else {
            BodyText("Updates and milestones from Aurorah CAN’s community work.")
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                categories.forEach { item ->
                    FilterChip(selected = item == category, onClick = { category = item }, label = { Text(item) })
                }
            }
            when {
                loading -> BodyText("Loading stories…")
                error != null -> RetryRow("Stories could not be loaded.") { refreshKey++ }
                stories.isEmpty() -> BodyText("No published stories are available yet.")
                else -> stories.filter { category == "All" || it.category == category }.forEach { story ->
                    StoryCard(story) { selectedStory = story }
                }
            }
            LinkButton("About Aurorah CAN") { onOpenWebsite("/about") }
        }
    }
}

@Composable
private fun ProfileScreen(
    modifier: Modifier,
    user: AppUser?,
    onUserChanged: (AppUser?) -> Unit,
    onOpenWebsite: (String) -> Unit
) {
    var isRegister by rememberSaveable { mutableStateOf(false) }
    var fullName by rememberSaveable { mutableStateOf("") }
    var email by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var phone by rememberSaveable { mutableStateOf("") }
    var profileName by rememberSaveable { mutableStateOf("") }
    var preferredContact by rememberSaveable { mutableStateOf("Email") }
    var profileLoading by remember { mutableStateOf(false) }
    var profileLoadError by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(user?.id) {
        if (user != null) {
            profileLoading = true
            try {
                val profile = withContext(Dispatchers.IO) {
                    Api.get("/api/auth/profile", user.token)
                }
                profileName = profile.optString("fullName", user.fullName)
                phone = profile.optString("phoneNumber", "").takeUnless { it == "null" }.orEmpty()
                preferredContact = profile.optJSONObject("preferences")
                    ?.optString("contactPreference", "Email")
                    ?.takeIf { it == "Email" || it == "Phone" } ?: "Email"
                profileLoadError = null
            } catch (e: IOException) {
                profileLoadError = e.message ?: "Your profile could not be loaded."
            } catch (e: JSONException) {
                profileLoadError = e.message ?: "The profile response was invalid."
            } finally {
                profileLoading = false
            }
        }
    }

    FormPage(modifier, "Profile") {
        if (user == null) {
            BodyText("Browse stories and learn about the organization without signing in. Sign in is only needed to submit a request, pledge, volunteer application, or offer to help.")
            message?.let { Notice(it, BrandPale, Brand) }
            SectionTitle(if (isRegister) "Create account" else "Sign in")
            if (isRegister) InputField("Full name", fullName, { fullName = it }, required = true)
            InputField("Email", email, { email = it }, keyboardType = KeyboardType.Email, required = true)
            InputField("Password", password, { password = it }, keyboardType = KeyboardType.Password, required = true, hint = if (isRegister) "At least 12 characters" else null)
            error?.let { ErrorNotice(it) }
            PrimaryButton(if (isRegister) "Create account" else "Sign in", busy) {
                error = when {
                    email.isBlank() || !email.contains("@") -> "Enter a valid email address."
                    password.isBlank() -> "Enter your password."
                    isRegister && fullName.isBlank() -> "Enter your full name."
                    isRegister && password.length < 12 -> "Password must be at least 12 characters."
                    else -> null
                }
                if (error == null) {
                    busy = true
                    scope.launch {
                        try {
                            val path = if (isRegister) "/api/auth/register" else "/api/auth/login"
                            val payload = JSONObject().put("email", email.trim()).put("password", password)
                            if (isRegister) payload.put("fullName", fullName.trim())
                            val response = withContext(Dispatchers.IO) { Api.post(path, payload) }
                            val account = response.getJSONObject("user")
                            onUserChanged(AppUser(
                                account.optInt("userId"),
                                account.optString("fullName"),
                                account.optString("email"),
                                account.optString("role"),
                                response.getString("token")
                            ))
                            message = response.optString("message")
                            password = ""
                            error = null
                        } catch (e: IOException) { error = e.message ?: "Authentication failed." }
                        catch (e: JSONException) { error = e.message ?: "The server returned an invalid response." }
                        finally { busy = false }
                    }
                }
            }
            TextButton(onClick = { isRegister = !isRegister; error = null }) {
                Text(if (isRegister) "Already have an account? Sign in" else "Need an account? Register", color = Brand)
            }
        } else {
            SectionTitle("Your details")
            BodyText(user.email)
            if (profileLoading) BodyText("Loading your profile…")
            profileLoadError?.let { ErrorNotice(it) }
            InputField("Full name", profileName, { profileName = it }, required = true)
            InputField("Phone number", phone, { phone = it }, keyboardType = KeyboardType.Phone)
            ChoiceChips("Preferred contact method", listOf("Email", "Phone"), preferredContact) {
                preferredContact = it
            }
            error?.let { ErrorNotice(it) }
            message?.let { Notice(it, Color(0xFFEAF7ED), Color(0xFF176B35)) }
            PrimaryButton("Save profile", busy) {
                if (profileName.isBlank()) error = "Enter your full name."
                else {
                    busy = true
                    scope.launch {
                        try {
                            withContext(Dispatchers.IO) {
                                Api.put("/api/auth/profile", JSONObject()
                                    .put("fullName", profileName.trim())
                                    .put("phoneNumber", phone.trim())
                                    .put("preferences", JSONObject().put("contactPreference", preferredContact)), user.token)
                            }
                            onUserChanged(user.copy(
                                fullName = profileName.trim(),
                                phone = phone.trim(),
                                preferredContact = preferredContact
                            ))
                            message = "Profile updated."
                            error = null
                        } catch (e: IOException) { error = e.message ?: "The profile could not be updated." }
                        catch (e: JSONException) { error = e.message ?: "The server returned an invalid response." }
                        finally { busy = false }
                    }
                }
            }
            TextButton(onClick = {
                val token = user.token
                onUserChanged(null)
                message = "Signing out…"
                scope.launch {
                    try {
                        withContext(Dispatchers.IO) {
                            Api.post("/api/auth/logout", JSONObject(), token)
                        }
                        message = "You have been signed out."
                    } catch (e: IOException) {
                        message = "Signed out on this device, but the server session could not be revoked. It will remain valid until it expires."
                    } catch (e: JSONException) {
                        message = "Signed out on this device, but the server returned an invalid response."
                    }
                }
            }) {
                Text("Sign out", color = Brand)
            }
            Notice("The mobile API does not currently provide request, donation, or volunteer submission history. These are not shown as trackable features.", BrandPale, Brand)
        }
        SectionTitle("About and information")
        LinkButton("About Aurorah CAN") { onOpenWebsite("/about") }
        LinkButton("Contact and location") { onOpenWebsite("/about") }
        LinkButton("Privacy and POPIA") { onOpenWebsite("/about#privacy-notice") }
        BodyText("Personal information is used to review submissions and contact you. Please only provide details needed for the task.")
    }
}

@Composable
private fun FormPage(modifier: Modifier, title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .background(Page)
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Text(title, color = Brand, fontSize = 28.sp, fontWeight = FontWeight.ExtraBold)
        content()
        Spacer(Modifier.height(8.dp))
    }
}

@Composable
private fun InputField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    keyboardType: KeyboardType = KeyboardType.Text,
    required: Boolean = false,
    minLines: Int = 1,
    hint: String? = null
) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(label + if (required) " *" else "", color = Ink, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier.fillMaxWidth(),
            placeholder = { if (hint != null) Text(hint) },
            keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
            visualTransformation = if (keyboardType == KeyboardType.Password) PasswordVisualTransformation() else VisualTransformation.None,
            minLines = minLines,
            singleLine = minLines == 1,
            shape = RoundedCornerShape(12.dp)
        )
    }
}

@Composable
private fun ChoiceChips(label: String, choices: List<String>, selected: String, onSelected: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(label, color = Ink, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            choices.forEach { choice ->
                FilterChip(selected = selected == choice, onClick = { onSelected(choice) }, label = { Text(choice) })
            }
        }
    }
}

@Composable
private fun PrimaryButton(text: String, busy: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        enabled = !busy,
        modifier = modifier.fillMaxWidth(),
        colors = ButtonDefaults.buttonColors(containerColor = Brand),
        shape = RoundedCornerShape(12.dp)
    ) { Text(if (busy) "Please wait…" else text, fontWeight = FontWeight.Bold) }
}

@Composable
private fun SectionTitle(text: String) {
    Text(text, color = Ink, fontSize = 20.sp, fontWeight = FontWeight.Bold)
}

@Composable
private fun BodyText(text: String) {
    Text(text, color = Muted, fontSize = 14.sp, lineHeight = 21.sp)
}

@Composable
private fun Notice(text: String, background: Color, foreground: Color) {
    Surface(color = background, shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
        Text(text, color = foreground, fontSize = 14.sp, lineHeight = 20.sp, modifier = Modifier.padding(14.dp))
    }
}

@Composable
private fun ErrorNotice(text: String) {
    Notice(text, Color(0xFFFFEEEE), Color(0xFF9D2424))
}

@Composable
private fun RetryRow(text: String, onRetry: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(text, color = Muted, fontSize = 14.sp, modifier = Modifier.weight(1f))
        TextButton(onClick = onRetry) { Text("Retry", color = Brand) }
    }
}

@Composable
private fun LinkButton(text: String, onClick: () -> Unit) {
    TextButton(onClick = onClick) { Text("$text  →", color = Brand, fontWeight = FontWeight.SemiBold) }
}

@Composable
private fun SignInPrompt(text: String, onSignIn: () -> Unit) {
    Notice(text, BrandPale, Brand)
    PrimaryButton("Go to Profile to sign in", false, onClick = onSignIn)
}

@Composable
private fun HubAction(title: String, description: String, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(16.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, color = Brand, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            BodyText(description)
        }
    }
}

@Composable
private fun InfoCard(title: String, description: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(16.dp)
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, color = Brand, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            BodyText(description)
        }
    }
}

@Composable
private fun NeedCard(need: CommunityNeed, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(16.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(need.title, color = Brand, fontSize = 16.sp, fontWeight = FontWeight.Bold)
            BodyText(need.description.ifBlank { "See how you can help with this community need." })
            Text(listOf(need.location, need.category, need.priority).filter { it.isNotBlank() }.joinToString(" · "), color = Muted, fontSize = 12.sp)
            Text("Offer to help  →", color = Brand, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
        }
    }
}

@Composable
private fun StoryCard(story: Story, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(16.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Column {
            StoryImage(story, Modifier.fillMaxWidth().height(190.dp))
            Column(Modifier.padding(17.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                Text(listOf(story.category, story.timestamp.take(10)).filter { it.isNotBlank() }.joinToString(" · ").uppercase(), color = BrandMid, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                Text(story.title, color = Ink, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                BodyText(story.summary)
                Text("Read story  →", color = Brand, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@Composable
private fun StoryImage(story: Story, modifier: Modifier = Modifier) {
    val imageUrl = story.imageUrl
    if (imageUrl.isNullOrBlank()) {
        StoryImagePlaceholder(modifier)
    } else {
        SubcomposeAsyncImage(
            model = imageUrl,
            contentDescription = "Image for ${story.title}",
            contentScale = ContentScale.Crop,
            modifier = modifier
        ) {
            when (painter.state) {
                is AsyncImagePainter.State.Loading,
                is AsyncImagePainter.State.Error -> StoryImagePlaceholder(Modifier.fillMaxSize())
                else -> SubcomposeAsyncImageContent()
            }
        }
    }
}

@Composable
private fun StoryImagePlaceholder(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier.background(BrandPale),
        contentAlignment = Alignment.Center
    ) {
        Icon(
            Icons.Filled.Article,
            contentDescription = null,
            tint = BrandMid,
            modifier = Modifier.size(48.dp)
        )
    }
}

private fun validate(first: String, second: String, third: String, agreed: Boolean): String? = when {
    first.isBlank() -> "Complete the first required field."
    second.isBlank() -> "Complete the second required field."
    third.isBlank() -> "Complete the third required field."
    !agreed -> "Please agree to the privacy information before submitting."
    else -> null
}

private object Api {
    suspend fun homeFeeds(): Quad<List<Story>, List<CommunityNeed>, String?, String?> = withContext(Dispatchers.IO) {
        var stories: List<Story> = emptyList()
        var needs: List<CommunityNeed> = emptyList()
        var newsError: String? = null
        var needsError: String? = null
        try { stories = stories() }
        catch (e: IOException) { newsError = e.message }
        catch (e: JSONException) { newsError = e.message }
        try { needs = needs() }
        catch (e: IOException) { needsError = e.message }
        catch (e: JSONException) { needsError = e.message }
        Quad(stories, needs, newsError, needsError)
    }

    fun stories(): List<Story> {
        val json = JSONArray(request("GET", "/api/news"))
        return (0 until json.length()).mapNotNull { index ->
            val item = json.optJSONObject(index) ?: return@mapNotNull null
            val title = item.optString("title").trim()
            if (title.isBlank()) null else Story(
                item.optInt("id"), title, item.optString("summary"),
                item.optString("category"), item.optString("timestamp"),
                resolveImageUrl(item.optString("image_url"))
            )
        }
    }

    fun needs(): List<CommunityNeed> {
        val json = JSONArray(request("GET", "/api/needs"))
        return (0 until json.length()).mapNotNull { index ->
            val item = json.optJSONObject(index) ?: return@mapNotNull null
            val title = item.optString("title").trim()
            if (title.isBlank()) null else CommunityNeed(
                item.optInt("needId"), title, item.optString("description"),
                item.optString("location"), item.optString("priority"), item.optString("category")
            )
        }
    }

    fun post(path: String, payload: JSONObject, token: String? = null): JSONObject =
        JSONObject(request("POST", path, payload, token))

    fun put(path: String, payload: JSONObject, token: String): JSONObject =
        JSONObject(request("PUT", path, payload, token))

    fun get(path: String, token: String): JSONObject =
        JSONObject(request("GET", path, token = token))

    private fun request(method: String, path: String, payload: JSONObject? = null, token: String? = null): String {
        val connection = URL("$SITE_BASE_URL$path").openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = 12_000
        connection.readTimeout = 12_000
        connection.setRequestProperty("Accept", "application/json")
        if (payload != null) {
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }
        if (token != null) connection.setRequestProperty("Authorization", "Bearer $token")
        try {
            if (payload != null) connection.outputStream.bufferedWriter(Charsets.UTF_8).use { it.write(payload.toString()) }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (code !in 200..299) {
                val detail = try {
                    val json = JSONObject(body)
                    json.optString("detail").takeIf { it.isNotBlank() }
                } catch (_: JSONException) { null }
                throw IOException(detail ?: "The server returned HTTP $code.")
            }
            return body
        } finally {
            connection.disconnect()
        }
    }
}

private data class Quad<A, B, C, D>(val first: A, val second: B, val third: C, val fourth: D)
