// static/firebase-init.js

// 1. PASTE YOUR firebaseConfig OBJECT FROM THE FIREBASE CONSOLE HERE
const firebaseConfig = {
  apiKey: "AIzaSyDbpRn_URhAlYLFSjNbx414o8MxYS2vLBc",
  authDomain: "bettims-donna-e334a.firebaseapp.com",
  projectId: "bettims-donna-e334a",
  storageBucket: "bettims-donna-e334a.firebasestorage.app",
  messagingSenderId: "272572895165",
  appId: "1:272572895165:web:5a64a28e3d238b7e900cd4",
  measurementId: "G-D0220GWLXF"
};

// Initialize Firebase
const analytics = getAnalytics(app);
// ------------------------------------------------------------------

// Initialize Firebase
const app = firebase.initializeApp(firebaseConfig);
const auth = firebase.auth();
const googleProvider = new firebase.auth.GoogleAuthProvider();

/**
 * This is the "bridge". It sends the Firebase token to our Flask backend.
 * The backend verifies it and creates a secure, HttpOnly session cookie.
 */
async function setSessionCookie(idToken) {
  const response = await fetch('/session-login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ idToken: idToken }),
  });
  return response.ok;
}

// --- These functions are called by the buttons on your HTML pages ---

/**
 * Handles Google Sign-In (for both login and register)
 */
async function signInWithGoogle() {
  try {
    const result = await auth.signInWithPopup(googleProvider);
    const idToken = await result.user.getIdToken();

    if (await setSessionCookie(idToken)) {
      // Check if this is a brand new user
      if (result.additionalUserInfo.isNewUser) {
        // Tell our backend to create their Firestore profile
        await fetch('/create-profile', { method: 'POST' }); 
      }
      // Send them to the onboarding/dashboard
      window.location.href = '/check-onboarding';
    } else {
      alert('Failed to log in to backend. Please try again.');
    }
  } catch (error) {
    console.error("Google sign-in error:", error);
    alert(error.message);
  }
}

/**
 * Handles Email & Password Sign-In
 */
async function signInWithEmail(email, password) {
  try {
    const result = await auth.signInWithEmailAndPassword(email, password);
    const idToken = await result.user.getIdToken();

    if (await setSessionCookie(idToken)) {
      window.location.href = '/check-onboarding';
    } else {
      alert('Failed to log in to backend. Please try again.');
    }
  } catch (error) {
    console.error("Email sign-in error:", error);
    // This will show "Invalid credentials" etc. to the user
    throw new Error(error.message);
  }
}

/**
 * Handles Email & Password Sign-Up
 */
async function signUpWithEmail(email, password) {
  try {
    const result = await auth.createUserWithEmailAndPassword(email, password);
    const idToken = await result.user.getIdToken();

    if (await setSessionCookie(idToken)) {
      // New user, tell our backend to create their Firestore profile
      await fetch('/create-profile', { method: 'POST' }); 
      window.location.href = '/check-onboarding';
    } else {
      alert('Failed to create backend session. Please try again.');
    }
  } catch (error) {
    console.error("Email sign-up error:", error);
    // This will show "Password too weak" etc. to the user
    throw new Error(error.message);
  }
}

/**
 * Handles Logout
 */
async function signOut() {
  try {
    await auth.signOut(); // Signs out of Firebase
    await fetch('/logout', { method: 'POST' }); // Deletes our Flask cookie
    window.location.href = '/login'; // Send to login page
  } catch (error) {
     console.error("Error signing out:", error);
     alert("Error signing out. Please clear your cookies.");
  }
}