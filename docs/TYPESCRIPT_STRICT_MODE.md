# TypeScript Strict Mode Guide

This document covers TypeScript strict mode configuration and best practices for the Samvara React Native client.

---

## Configuration

**File:** `client/tsconfig.json`

Samvara uses the strictest possible TypeScript configuration for production safety:

```json
{
  "compilerOptions": {
    "strict": true,                          // Enable all strict mode flags
    "noImplicitAny": true,                   // No implicit any
    "noUnusedLocals": true,                  // Error on unused variables
    "noUnusedParameters": true,              // Error on unused parameters
    "noImplicitReturns": true,               // All code paths return
    "noFallthroughCasesInSwitch": true,      // No empty switch cases
    "noUncheckedIndexedAccess": true,        // Index access returns | undefined
    "noImplicitThis": true,                  // No implicit any for this
    "noPropertyAccessFromIndexSignature": true, // Index signature strict access
    "useUnknownInCatchVariables": true       // Caught errors are unknown
  }
}
```

### What Each Flag Does

| Flag | Prevents | Example |
|------|----------|---------|
| `strict` | All other flags (alias) | `const x: any = ...` |
| `noImplicitAny` | Inferring any type | `function foo(x) {}` |
| `noUnusedLocals` | Unused variables | `const x = 5; // unused` |
| `noUnusedParameters` | Unused params | `function(x, unused) {}` |
| `noImplicitReturns` | Missing returns | `if (x) return 5; // no else` |
| `noFallthroughCasesInSwitch` | Empty case blocks | `case 1: case 2: x();` |
| `noUncheckedIndexedAccess` | Unsafe indexing | `arr[0].property` → `arr[0]?.property` |
| `noImplicitThis` | Untyped this | `function() { this.x }` |
| `noPropertyAccessFromIndexSignature` | Loose object access | `obj["key"]` (instead of `obj.key`) |
| `useUnknownInCatchVariables` | Unsafe catch errors | `catch (e) { e.message }` |

---

## Best Practices

### 1. Type All Function Parameters

❌ **Bad:**
```typescript
function createCharge(amount, description) {
  // ...
}
```

✅ **Good:**
```typescript
function createCharge(amount: number, description: string): Promise<ChargeResult> {
  // ...
}
```

**Why:** Prevents passing wrong types; enables IDE autocomplete and refactoring.

### 2. Explicit Return Types

❌ **Bad:**
```typescript
function getStatus() {  // Inferred as unknown
  if (condition) {
    return { charged: true };
  }
  // Missing return in other path!
}
```

✅ **Good:**
```typescript
function getStatus(): BillingStatus {  // Explicit type + all paths return
  if (condition) {
    return { charged: true, amount: 0, ... };
  }
  return { charged: false, amount: 0, ... };
}
```

**Why:** Catches logic errors and documents intent.

### 3. Handle Undefined Index Access

❌ **Bad:**
```typescript
const cards = response.data.cards;  // May be undefined
const first = cards[0].brand;       // cards may be undefined, [0] may not exist
```

✅ **Good:**
```typescript
const cards = response.data?.cards ?? [];
const first = cards[0]?.brand;      // Safe optional chaining
```

**Why:** Prevents "Cannot read property of undefined" runtime errors.

### 4. Type Union Results Explicitly

❌ **Bad:**
```typescript
function chargeCard(amount: number) {
  try {
    return stripe.charge(amount);  // May throw or return
  } catch (e) {
    return null;  // Now return type is confusing
  }
}
```

✅ **Good:**
```typescript
type ChargeOutcome = 
  | { ok: true; charge: Charge }
  | { ok: false; error: BillingError };

function chargeCard(amount: number): ChargeOutcome {
  try {
    return { ok: true, charge: await stripe.charge(amount) };
  } catch (e) {
    return { ok: false, error: normalizeBillingError(e) };
  }
}

// Usage is explicit:
const result = chargeCard(50);
if (result.ok) {
  console.log("Charged:", result.charge);
} else {
  console.error("Failed:", result.error);
}
```

**Why:** Eliminates null-checking confusion; makes error paths explicit.

### 5. Catch Errors as Unknown

❌ **Bad:**
```typescript
try {
  await client.post("/api/charge");
} catch (e) {
  console.error(e.message);  // e might not have message property
}
```

✅ **Good:**
```typescript
try {
  await client.post("/api/charge");
} catch (e) {
  const error = e instanceof Error ? e : new Error(String(e));
  console.error(error.message);
}
```

**Why:** Not all thrown values are Error objects (could be string, null, etc).

### 6. Avoid Optional Parameters Unless Necessary

❌ **Bad:**
```typescript
function setupPayment(
  customerId?: string,
  intentId?: string,
  amount?: number
) {
  // Caller might forget to pass required fields
}
```

✅ **Good:**
```typescript
interface PaymentSetup {
  customerId: string;
  intentId: string;
  amount: number;
}

function setupPayment(setup: PaymentSetup) {
  // All fields required by type
}
```

**Why:** Required parameters caught at compile time, not runtime.

### 7. Use Enums for Constants

❌ **Bad:**
```typescript
const status = "succeeded";  // Could be misspelled: "succeded"
if (charge.status === "succeded") { }  // Typo not caught
```

✅ **Good:**
```typescript
enum ChargeStatus {
  Pending = "pending",
  Succeeded = "succeeded",
  RequiresAction = "requires_action",
}

const status: ChargeStatus = ChargeStatus.Succeeded;
if (charge.status === ChargeStatus.Succeeded) { }  // Type-safe
```

**Why:** Autocomplete + typo prevention for string constants.

### 8. Document Complex Types

✅ **Good:**
```typescript
/**
 * Result of billing operation with status and optional error.
 * 
 * @example
 * const result = await billingClient.createSetupIntent();
 * if (result.error) {
 *   Alert.alert("Failed", result.error.userMessage);
 * }
 */
export interface BillingResult<T> {
  data?: T;
  error?: BillingError;
  retry: () => Promise<BillingResult<T>>;
}
```

**Why:** Helps future readers understand intent and usage.

---

## Common Strict Mode Issues & Fixes

### Issue 1: "Property might be undefined"

```typescript
// Error: Object is possibly 'undefined'
const brand = response.data.card.brand;
```

**Fix:**
```typescript
const brand = response.data?.card?.brand;
```

### Issue 2: "Not all code paths return"

```typescript
// Error: Function lacks ending return statement
function status() {
  if (x) return "success";
  if (y) return "pending";
  // Missing case!
}
```

**Fix:**
```typescript
function status(): "success" | "pending" | "failed" {
  if (x) return "success";
  if (y) return "pending";
  return "failed";  // All paths covered
}
```

### Issue 3: "Parameter not used"

```typescript
// Error: 'unused' is declared but its value is never read
function onChargeComplete(charge: Charge, unused: string) {
  console.log(charge.amount);
}
```

**Fix:** If truly unused, prefix with `_`:
```typescript
function onChargeComplete(charge: Charge, _unused: string) {
  console.log(charge.amount);
}
```

Or remove if not needed:
```typescript
function onChargeComplete(charge: Charge) {
  console.log(charge.amount);
}
```

### Issue 4: "Property access from index signature"

```typescript
// Error: Property 'brand' comes from an index signature, so it must be accessed with ['brand']
const obj: { [key: string]: string } = { brand: "visa" };
console.log(obj.brand);  // Error
```

**Fix:** Use index notation:
```typescript
console.log(obj["brand"]);
```

Or use typed interface:
```typescript
interface Card {
  brand: string;
}
const card: Card = { brand: "visa" };
console.log(card.brand);  // OK
```

---

## IDE Integration

### VS Code Setup

1. **Install TypeScript:**
   ```bash
   npm install --save-dev typescript
   ```

2. **Configure TypeScript Version** (VS Code settings.json):
   ```json
   {
     "typescript.tsdk": "node_modules/typescript/lib",
     "typescript.enablePromptUseWorkspaceTsdk": true
   }
   ```

3. **Enable strict mode warnings:**
   ```json
   {
     "[typescript]": {
       "editor.defaultFormatter": "esbenp.prettier-vscode",
       "editor.formatOnSave": true
     }
   }
   ```

### Pre-commit Hook

Lint TypeScript before commit:

```bash
#!/bin/bash
# .git/hooks/pre-commit
npx tsc --noEmit || {
  echo "TypeScript errors found. Fix before committing."
  exit 1
}
```

---

## Migration Strategy

If adding strict mode to existing codebase:

1. **Run with `--noEmit`** to find all errors without changing files:
   ```bash
   npx tsc --noEmit
   ```

2. **Fix incrementally** by compiler category:
   ```bash
   # Category 1: No implicit any
   # Category 2: Unused variables
   # Category 3: Missing return types
   ```

3. **Use escape hatch temporarily** with `// @ts-expect-error`:
   ```typescript
   // @ts-expect-error: Library types incomplete
   const response = await badlyTypedLibrary.call();
   ```
   Then create GitHub issue to fix properly later.

4. **Audit and commit:**
   ```bash
   git add .
   git commit -m "Enable TypeScript strict mode"
   ```

---

## Type Definitions for Billing

### Payment Status Types

```typescript
export enum PaymentStatus {
  Pending = "pending",
  RequiresAction = "requires_action",
  Succeeded = "succeeded",
  Failed = "failed",
}

export interface Payment {
  id: string;
  status: PaymentStatus;
  amount: number;
  createdAt: Date;
}
```

### API Response Types

```typescript
export interface ApiResponse<T> {
  data?: T;
  error?: {
    code: string;
    message: string;
  };
}

export interface BillingStatusResponse {
  provider: "samvara" | "beeminder";
  hasPaymentMethod: boolean;
  cardDisplay: string | null;
  publishableKey: string;
}
```

### Error Types

```typescript
export interface BillingError {
  type: "network" | "validation" | "server" | "user_action";
  message: string;
  userMessage: string;
  retryable: boolean;
}

export class NetworkError extends Error implements BillingError {
  type = "network" as const;
  retryable = true;
  userMessage = "Connection failed. Check your internet and try again.";
  
  constructor(message: string) {
    super(message);
    this.name = "NetworkError";
  }
}
```

---

## Validation Checklist

Before committing TypeScript code:

- [ ] No `any` types (use specific types instead)
- [ ] All function parameters typed
- [ ] All function return types explicit
- [ ] All code paths have return statement
- [ ] No unused variables or parameters
- [ ] All error cases handled (`try/catch` with proper typing)
- [ ] All optional chaining used (`?.`)
- [ ] All nullish coalescing used (`??`)
- [ ] Type guards in conditionals
- [ ] No `@ts-ignore` comments (use `@ts-expect-error` with reason)

---

## References

- [TypeScript Handbook: Strict Mode](https://www.typescriptlang.org/docs/handbook/2/narrowing.html)
- [TypeScript Configuration](https://www.typescriptlang.org/tsconfig)
- [Effect TypeScript](https://effect.website/) — Advanced typing patterns
- [Total TypeScript](https://www.totaltypescript.com/) — Learning resource
