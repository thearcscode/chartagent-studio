import { SignIn } from "@clerk/react";

export function SignInPage() {
  return (
    <main className="auth-screen">
      <SignIn routing="path" path="/sign-in" signUpUrl="/sign-up" />
    </main>
  );
}
