import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'

function isNetworkError(error) {
  return (
    !navigator.onLine ||
    error instanceof TypeError ||
    error instanceof SyntaxError ||
    error.status >= 500
  )
}

function readPreferredTheme() {
  try {
    return window.localStorage.getItem('wellnest-theme') === 'dark'
      ? 'dark'
      : 'light'
  } catch (error) {
    console.error('Could not read the saved dashboard theme.', error)
    return 'light'
  }
}

function getOfflineOwnerKey(user) {
  return String(user.id ?? user.username)
}

function readCachedSession() {
  try {
    const cached = sessionStorage.getItem('wellnest-session')
    return cached ? JSON.parse(cached) : null
  } catch (error) {
    console.error('Could not read the cached offline session.', error)
    sessionStorage.removeItem('wellnest-session')
    return null
  }
}

function saveCachedSession(user, branches) {
  try {
    sessionStorage.setItem('wellnest-session', JSON.stringify({ user, branches }))
    return true
  } catch (error) {
    console.error('Could not save the offline session cache.', error)
    return false
  }
}

function saveCachedUser(user) {
  const cachedSession = readCachedSession()
  const branches = cachedSession?.user?.id === user.id
    ? cachedSession.branches || []
    : []
  return saveCachedSession(user, branches)
}

function branchCacheKey(ownerKey, branchId) {
  return `wellnest-branch:${ownerKey}:${branchId}`
}

function readCachedBranch(ownerKey, branchId) {
  const key = branchCacheKey(ownerKey, branchId)
  try {
    const cached = sessionStorage.getItem(key)
    return cached ? JSON.parse(cached) : null
  } catch (error) {
    console.error('Could not read the cached branch inventory.', error)
    sessionStorage.removeItem(key)
    return null
  }
}

function saveCachedBranch(ownerKey, branchId, inventory, products) {
  try {
    sessionStorage.setItem(
      branchCacheKey(ownerKey, branchId),
      JSON.stringify({ inventory, products }),
    )
    return true
  } catch (error) {
    console.error('Could not save the cached branch inventory.', error)
    return false
  }
}

function openOfflineDraftStore() {
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) {
      reject(new Error('This browser does not support safely storing offline POS drafts.'))
      return
    }
    const request = window.indexedDB.open('wellnest-offline', 1)
    request.onupgradeneeded = () => {
      request.result.createObjectStore('drafts', { keyPath: 'id' })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('Could not open the offline POS queue.'))
  })
}

async function getOfflineDrafts(ownerKey) {
  const database = await openOfflineDraftStore()
  return new Promise((resolve, reject) => {
    const request = database.transaction('drafts', 'readonly').objectStore('drafts').getAll()
    request.onsuccess = () => {
      database.close()
      resolve(request.result.filter((draft) => draft.ownerKey === ownerKey))
    }
    request.onerror = () => {
      database.close()
      reject(request.error || new Error('Could not read the offline POS queue.'))
    }
  })
}

async function saveOfflineDraft(draft) {
  const database = await openOfflineDraftStore()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction('drafts', 'readwrite')
    transaction.objectStore('drafts').put(draft)
    transaction.oncomplete = () => {
      database.close()
      resolve()
    }
    transaction.onerror = () => {
      database.close()
      reject(transaction.error || new Error('Could not save this POS draft on the device.'))
    }
  })
}

async function deleteOfflineDraft(id) {
  const database = await openOfflineDraftStore()
  return new Promise((resolve, reject) => {
    const transaction = database.transaction('drafts', 'readwrite')
    transaction.objectStore('drafts').delete(id)
    transaction.oncomplete = () => {
      database.close()
      resolve()
    }
    transaction.onerror = () => {
      database.close()
      reject(transaction.error || new Error('Could not remove the offline POS draft.'))
    }
  })
}

async function apiRequest(path, { method = 'GET', body } = {}) {
  const headers = {}
  const isFormData = body instanceof FormData
  if (body !== undefined && !isFormData) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') {
    const csrfResponse = await fetch('/api/auth/csrf/', { credentials: 'include' })
    const csrfData = await csrfResponse.json()
    if (!csrfResponse.ok) {
      throw new Error(csrfData.detail || 'Could not prepare a secure request.')
    }
    headers['X-CSRFToken'] = csrfData.csrfToken
  }

  const response = await fetch(path, {
    method,
    credentials: 'include',
    headers,
    body: body === undefined ? undefined : isFormData ? body : JSON.stringify(body),
  })
  let data
  try {
    data = await response.json()
  } catch (error) {
    if (error instanceof SyntaxError && !response.ok) {
      const requestError = new Error(`The server could not complete the request (${response.status}).`)
      requestError.status = response.status
      throw requestError
    }
    throw error
  }
  if (!response.ok) {
    const error = new Error(data.detail || 'The request failed.')
    error.code = data.code
    error.status = response.status
    throw error
  }
  return data
}

function LoginScreen({
  username,
  setUsername,
  password,
  setPassword,
  error,
  isSubmitting,
  onSubmit,
}) {
  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={onSubmit}>
        <h1>Wellnest</h1>
        <p>Sign in to your pharmacy inventory</p>
        <label>
          Username
          <input
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}

const emptyBatch = {
  sku: '',
  name: '',
  category: '',
  batch: '',
  quantity: '',
  reorderLevel: '',
  expiry: '',
  supplier: '',
  purchaseCost: '',
  sellingPrice: '',
  witnessId: '',
}

const emptyDispense = {
  sku: '',
  transactionType: 'Sale',
  quantity: '',
  recipient: '',
  amountReceived: '',
  paymentMethod: 'Cash',
  receiptEmail: '',
}

const emptyStockCount = {
  batch: '',
  quantity: '',
  reason: '',
  witnessId: '',
}

const emptySupplierInvoice = {
  supplier: '',
  invoiceNumber: '',
  invoiceAmount: '',
  amountPaid: '0',
  dueDate: '',
  purchaseOrderId: '',
  originalDocument: null,
}

const emptySupplierPayment = {
  invoiceId: '',
  amount: '',
  method: '',
}

const emptyCustomerPayment = {
  saleId: '',
  amount: '',
  method: '',
}

const emptyPrescription = {
  reference: '',
  patientReference: '',
  prescriberName: '',
  prescriberRegistration: '',
  issuedDate: '',
  expiresDate: '',
  sku: '',
  quantity: '',
  directions: '',
}

const emptyPrescriptionDispense = {
  lineKey: '',
  quantity: '',
  amountReceived: '0',
  paymentMethod: '',
  witnessId: '',
}

const emptyPurchaseOrder = {
  supplierId: '',
  expectedDate: '',
  sku: '',
  quantity: '',
  unitCost: '',
}

const emptyPurchaseReceipt = {
  orderId: '',
  lineId: '',
  quantity: '',
  batch: '',
  expiry: '',
  sellingPrice: '',
  witnessId: '',
}

const emptyTransfer = {
  destinationBranchId: '',
  sku: '',
  quantity: '',
  witnessId: '',
}

const emptyProduct = {
  name: '',
  category: '',
  productType: 'medicine',
  unit: 'unit',
  brand: '',
  skinType: '',
  skinConcerns: '',
  keyIngredients: '',
  usageInstructions: '',
  warnings: '',
  periodAfterOpeningMonths: '',
  requiresPrescription: false,
  isControlled: false,
  controlledSchedule: '',
}

const emptySupplier = { name: '', contactName: '', email: '', phone: '', address: '' }
const emptySupplierProduct = {
  sku: '',
  supplierId: '',
  supplierSku: '',
  unitCost: '',
  leadTimeDays: '0',
  isPreferred: true,
}

function getStockStatus(medicine, today = new Date()) {
  if (medicine.expiry && new Date(`${medicine.expiry}T00:00:00`) < today) {
    return 'Expired'
  }
  if (medicine.quantity === 0) return 'Out of stock'
  if (medicine.quantity <= medicine.reorderLevel) return 'Low stock'
  return 'In stock'
}


function getSupplierInvoiceStatus(invoice) {
  const balance = invoice.invoiceAmount - invoice.amountPaid
  const today = new Date().toISOString().slice(0, 10)

  if (balance <= 0) return 'Paid'
  if (invoice.dueDate && invoice.dueDate < today) return 'Overdue'
  if (invoice.amountPaid > 0) return 'Partially paid'
  return 'Unpaid'
}

function getSalePaymentStatus(sale) {
  if (sale.approvalStatus === 'pending') return 'Awaiting pharmacist approval'
  if (sale.approvalStatus === 'rejected') return 'Rejected'
  if (sale.balanceDue <= 0) return 'Paid'
  if (sale.amountReceived > 0) return 'Partially paid'
  return 'Unpaid'
}

function getSaleAllocation(inventory, sku, quantity, asOf) {
  const eligibleBatches = inventory
    .filter(
      (item) =>
        item.sku === sku &&
        item.quantity > 0 &&
        (
          (item.expiry && new Date(`${item.expiry}T00:00:00`) >= asOf)
          || (!item.expiry && item.productType === 'skin_care')
        )
    )
    .sort((first, second) => {
      if (!first.expiry) return second.expiry ? 1 : 0
      if (!second.expiry) return -1
      return first.expiry.localeCompare(second.expiry)
    })
  const availableQuantity = eligibleBatches.reduce(
    (total, item) => total + item.quantity,
    0,
  )
  let remaining = quantity
  const allocations = []

  for (const item of eligibleBatches) {
    if (remaining === 0) break
    const quantityFromBatch = Math.min(item.quantity, remaining)
    allocations.push({ batch: item, quantity: quantityFromBatch })
    remaining -= quantityFromBatch
  }

  const saleAmount = allocations.reduce(
    (total, allocation) =>
      total + allocation.quantity * Number(allocation.batch.sellingPrice || 0),
    0,
  )

  return { availableQuantity, allocations, remaining, saleAmount }
}

function App() {
  const [activePage, setActivePage] = useState('Overview')
  const [theme, setTheme] = useState(readPreferredTheme)
  const [currentTime, setCurrentTime] = useState(() => new Date())
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [inventory, setInventory] = useState([])
  const [showAddForm, setShowAddForm] = useState(false)
  const [newBatch, setNewBatch] = useState(emptyBatch)
  const [formError, setFormError] = useState('')
  const [stockMovements, setStockMovements] = useState([])
  const [showDispenseForm, setShowDispenseForm] = useState(false)
  const [dispenseForm, setDispenseForm] = useState(emptyDispense)
  const [dispenseError, setDispenseError] = useState('')
  const [prescriptionRedirectSku, setPrescriptionRedirectSku] = useState('')
  const [showStockCountForm, setShowStockCountForm] = useState(false)
  const [stockCountForm, setStockCountForm] = useState(emptyStockCount)
  const [stockCountError, setStockCountError] = useState('')
  const [sales, setSales] = useState([])
  const [supplierInvoices, setSupplierInvoices] = useState([])
  const [supplierPayments, setSupplierPayments] = useState([])
  const [showSupplierInvoiceForm, setShowSupplierInvoiceForm] = useState(false)
  const [supplierInvoiceForm, setSupplierInvoiceForm] = useState(emptySupplierInvoice)
  const [supplierInvoiceError, setSupplierInvoiceError] = useState('')
  const [showSupplierPaymentForm, setShowSupplierPaymentForm] = useState(false)
  const [supplierPaymentForm, setSupplierPaymentForm] = useState(emptySupplierPayment)
  const [supplierPaymentError, setSupplierPaymentError] = useState('')
  const [customerPayments, setCustomerPayments] = useState([])
  const [showCustomerPaymentForm, setShowCustomerPaymentForm] = useState(false)
  const [customerPaymentForm, setCustomerPaymentForm] = useState(emptyCustomerPayment)
  const [customerPaymentError, setCustomerPaymentError] = useState('')
  const [currentUser, setCurrentUser] = useState(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [isOnline, setIsOnline] = useState(() => navigator.onLine)
  const [offlineDrafts, setOfflineDrafts] = useState([])
  const isSyncingOfflineDrafts = useRef(false)
  const supplierInvoiceDocumentRef = useRef(null)
  const [authError, setAuthError] = useState('')
  const [loginUsername, setLoginUsername] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginSubmitting, setLoginSubmitting] = useState(false)
  const [branches, setBranches] = useState([])
  const [activeBranchId, setActiveBranchId] = useState('')
  const [analyticsBranchId, setAnalyticsBranchId] = useState('')
  const [loadedBranchId, setLoadedBranchId] = useState('')
  const [dataError, setDataError] = useState('')
  const [products, setProducts] = useState([])
  const [suppliers, setSuppliers] = useState([])
  const [branchStaff, setBranchStaff] = useState([])
  const [prescriptions, setPrescriptions] = useState([])
  const [purchaseOrders, setPurchaseOrders] = useState([])
  const [reorderSuggestions, setReorderSuggestions] = useState([])
  const [transfers, setTransfers] = useState([])
  const [analytics, setAnalytics] = useState(null)
  const [replenishmentForecast, setReplenishmentForecast] = useState(null)
  const [workflowError, setWorkflowError] = useState('')
  const [workflowNotice, setWorkflowNotice] = useState('')
  const [receiptSaleId, setReceiptSaleId] = useState('')
  const [saleRejectionReasons, setSaleRejectionReasons] = useState({})
  const [prescriptionForm, setPrescriptionForm] = useState(emptyPrescription)
  const [prescriptionDispenseForm, setPrescriptionDispenseForm] = useState(emptyPrescriptionDispense)
  const [purchaseOrderForm, setPurchaseOrderForm] = useState(emptyPurchaseOrder)
  const [purchaseReceiptForm, setPurchaseReceiptForm] = useState(emptyPurchaseReceipt)
  const [transferForm, setTransferForm] = useState(emptyTransfer)
  const [transferReceiptQuantities, setTransferReceiptQuantities] = useState({})
  const [transferReceiptBatches, setTransferReceiptBatches] = useState({})
  const [transferWitnessId, setTransferWitnessId] = useState('')
  const [productForm, setProductForm] = useState(emptyProduct)
  const [supplierForm, setSupplierForm] = useState(emptySupplier)
  const [supplierProductForm, setSupplierProductForm] = useState(emptySupplierProduct)
  const [reportStart, setReportStart] = useState(() => {
    const start = new Date()
    start.setDate(start.getDate() - 30)
    return start.toISOString().slice(0, 10)
  })
  const [reportEnd, setReportEnd] = useState(() => new Date().toISOString().slice(0, 10))
  const [today] = useState(() => {
    const currentDate = new Date()
    currentDate.setHours(0, 0, 0, 0)
    return currentDate
  })
  const reportBranchId = currentUser?.isSuperuser ? analyticsBranchId : activeBranchId
  const currentHour = currentTime.getHours()
  const timeGreeting = currentHour < 12
    ? 'Good morning'
    : currentHour < 17
      ? 'Good afternoon'
      : 'Good evening'

  useEffect(() => {
    const timerId = window.setInterval(() => setCurrentTime(new Date()), 60_000)
    return () => window.clearInterval(timerId)
  }, [])

  const refreshBranchData = useCallback(async (branchId = activeBranchId, isCurrent = () => true) => {
    if (!branchId) return
    const query = `?branchId=${encodeURIComponent(branchId)}`
    const membership = currentUser?.memberships.find(
      (item) => String(item.branchId) === String(branchId),
    )
    const canReviewClinicalWork = ['pharmacist', 'branch_manager'].includes(membership?.role)
    const canManageBranch = membership?.role === 'branch_manager'
    const [data, productData, supplierData, staffData, prescriptionData, orderData, transferData, reorderData] =
      await Promise.all([
        apiRequest(`/api/data/${query}`),
        apiRequest('/api/products/'),
        canManageBranch ? apiRequest('/api/suppliers/') : Promise.resolve({ suppliers: [] }),
        canManageBranch ? apiRequest(`/api/branch-staff/${query}`) : Promise.resolve({ members: [] }),
        canReviewClinicalWork ? apiRequest(`/api/prescriptions/${query}`) : Promise.resolve({ prescriptions: [] }),
        canReviewClinicalWork ? apiRequest(`/api/purchase-orders/${query}`) : Promise.resolve({ purchaseOrders: [] }),
        canManageBranch ? apiRequest(`/api/transfers/${query}`) : Promise.resolve({ transfers: [] }),
        canReviewClinicalWork ? apiRequest(`/api/reorder-suggestions/${query}`) : Promise.resolve({ suggestions: [] }),
      ])
    if (isCurrent()) {
      setInventory(data.inventory)
      setStockMovements(data.stockMovements)
      setSales(data.sales)
      setSupplierInvoices(data.supplierInvoices)
      setSupplierPayments(data.supplierPayments)
      setCustomerPayments(data.customerPayments)
      setProducts(productData.products)
      setSuppliers(supplierData.suppliers)
      setBranchStaff(staffData.members)
      setPrescriptions(prescriptionData.prescriptions)
      setPurchaseOrders(orderData.purchaseOrders)
      setTransfers(transferData.transfers)
      setReorderSuggestions(reorderData.suggestions)
      if (!saveCachedBranch(
        getOfflineOwnerKey(currentUser),
        branchId,
        data.inventory,
        productData.products,
      )) {
        setWorkflowNotice('Browser storage is unavailable; inventory cannot be shown offline after a reload.')
      }
    }
  }, [activeBranchId, currentUser])

  useEffect(() => {
    function updateConnectionStatus() {
      setIsOnline(navigator.onLine)
    }

    window.addEventListener('online', updateConnectionStatus)
    window.addEventListener('offline', updateConnectionStatus)
    return () => {
      window.removeEventListener('online', updateConnectionStatus)
      window.removeEventListener('offline', updateConnectionStatus)
    }
  }, [])

  useEffect(() => {
    if (!import.meta.env.PROD || !('serviceWorker' in navigator)) return

    navigator.serviceWorker.register('/service-worker.js').catch((error) => {
      console.error('Could not register the offline app shell.', error)
      setWorkflowNotice('Offline app-shell caching is unavailable in this browser session.')
    })
  }, [])

  useEffect(() => {
    if (!currentUser) return
    let cancelled = false

    async function loadAndSyncOfflineDrafts() {
      const ownerKey = getOfflineOwnerKey(currentUser)
      const queuedDrafts = await getOfflineDrafts(ownerKey)
      if (cancelled) return
      setOfflineDrafts(queuedDrafts.sort((first, second) => first.createdAt.localeCompare(second.createdAt)))
      if (!isOnline || isSyncingOfflineDrafts.current) return

      isSyncingOfflineDrafts.current = true
      let acceptedCount = 0
      try {
        for (const draft of queuedDrafts) {
          if (draft.status !== 'pending') continue
          let submitError = null
          try {
            await apiRequest('/api/dispense/', {
              method: 'POST',
              body: draft.payload,
            })
          } catch (error) {
            if (isNetworkError(error)) {
              setIsOnline(false)
              break
            }
            submitError = error
          }
          if (submitError) {
            await saveOfflineDraft({
              ...draft,
              status: 'needs_review',
              error: submitError.message || 'The server rejected this queued sale.',
            })
            continue
          }

          await deleteOfflineDraft(draft.id)
          acceptedCount += 1
          if (String(draft.branchId) === String(activeBranchId)) {
            try {
              await refreshBranchData(draft.branchId)
            } catch (error) {
              if (!isNetworkError(error)) {
                setWorkflowError(error.message || 'The queued sale was submitted, but branch data could not be refreshed.')
              } else {
                setIsOnline(false)
                setWorkflowNotice('A queued sale was submitted, but branch data could not be refreshed. Reload the dashboard when the connection is stable.')
                break
              }
            }
          }
        }
      } finally {
        isSyncingOfflineDrafts.current = false
      }

      const remainingDrafts = await getOfflineDrafts(ownerKey)
      if (!cancelled) {
        setOfflineDrafts(remainingDrafts.sort((first, second) => first.createdAt.localeCompare(second.createdAt)))
        if (acceptedCount > 0) {
          setWorkflowNotice(`${acceptedCount} queued POS sale${acceptedCount === 1 ? '' : 's'} recorded after reconnection; stock and payment have been posted.`)
        }
      }
    }

    loadAndSyncOfflineDrafts().catch((error) => {
      if (!cancelled) setWorkflowError(error.message || 'Could not load or sync queued POS drafts.')
    })

    return () => {
      cancelled = true
    }
  }, [currentUser, isOnline, activeBranchId, refreshBranchData])

  useEffect(() => {
    if (!currentUser) return
    let cancelled = false

    apiRequest('/api/branches/')
      .then(({ branches: availableBranches }) => {
        if (cancelled) return
        setBranches(availableBranches)
        if (!saveCachedSession(currentUser, availableBranches)) {
          setWorkflowNotice('Browser storage is unavailable; this session cannot resume offline after a reload.')
        }
        setActiveBranchId((current) => {
          if (
            currentUser.memberships.some(
              (membership) => String(membership.branchId) === String(current),
            ) &&
            availableBranches.some((branch) => String(branch.id) === String(current))
          ) {
            return String(current)
          }
          const membershipBranch = currentUser.memberships.find((membership) =>
            availableBranches.some((branch) => branch.id === membership.branchId)
          )?.branchId
          return String(membershipBranch ?? '')
        })
        setAnalyticsBranchId((current) => {
          if (availableBranches.some((branch) => String(branch.id) === String(current))) {
            return String(current)
          }
          return String(availableBranches[0]?.id ?? '')
        })
        if (currentUser.isSuperuser && currentUser.memberships.length === 0) {
          setActivePage('Reports')
        }
      })
      .catch((error) => {
        if (cancelled) return
        if (isNetworkError(error)) {
          const cachedSession = readCachedSession()
          if (cachedSession?.user?.id === currentUser.id && cachedSession.branches?.length) {
            setBranches(cachedSession.branches)
            const homeBranchId = currentUser.memberships.find((membership) =>
              cachedSession.branches.some(
                (branch) => String(branch.id) === String(membership.branchId),
              ),
            )?.branchId
            setActiveBranchId(String(homeBranchId ?? ''))
            setAnalyticsBranchId(String(cachedSession.branches[0].id))
            if (currentUser.isSuperuser && currentUser.memberships.length === 0) {
              setActivePage('Reports')
            }
            setIsOnline(false)
            setWorkflowNotice('Offline mode: using this user’s previously loaded branch data. Stock-changing actions require a connection.')
            return
          }
        }
        setDataError(error.message || 'Could not load your branches.')
      })

    return () => {
      cancelled = true
    }
  }, [currentUser])

  useEffect(() => {
    if (!currentUser || !activeBranchId) return
    let cancelled = false

    Promise.resolve()
      .then(() => {
        if (cancelled) return null
        return refreshBranchData(activeBranchId, () => !cancelled)
      })
      .then(() => {
        if (!cancelled) {
          setDataError('')
          setLoadedBranchId(activeBranchId)
        }
      })
      .catch((error) => {
        if (!cancelled) {
          if (isNetworkError(error)) {
            setIsOnline(false)
            const cachedBranch = readCachedBranch(getOfflineOwnerKey(currentUser), activeBranchId)
            if (cachedBranch) {
              const { inventory: cachedInventory, products: cachedProducts } = cachedBranch
              setInventory(cachedInventory)
              setProducts(cachedProducts)
              setDataError('')
              setWorkflowNotice('Offline mode: displaying cached inventory. Stock-changing and clinical actions are unavailable until reconnection.')
              setLoadedBranchId(activeBranchId)
              return
            }
            setInventory([])
            setProducts([])
          }
          setDataError(error.message || 'Could not load branch data.')
          setLoadedBranchId(activeBranchId)
        }
      })

    return () => {
      cancelled = true
    }
  }, [currentUser, activeBranchId, refreshBranchData])

  async function saveBranchAction(path, values) {
    const body = values instanceof FormData
      ? values
      : { ...values, branchId: Number(activeBranchId) }
    if (body instanceof FormData) {
      body.set('branchId', String(activeBranchId))
    }
    const response = await apiRequest(path, {
      method: 'POST',
      body,
    })
    await refreshBranchData(activeBranchId)
    return response
  }

  function toggleTheme() {
    const nextTheme = theme === 'dark' ? 'light' : 'dark'
    setTheme(nextTheme)
    try {
      window.localStorage.setItem('wellnest-theme', nextTheme)
      setWorkflowNotice('')
    } catch (error) {
      console.error('Could not save the dashboard theme preference.', error)
      setWorkflowNotice('Theme changed for this session, but the preference could not be saved in browser storage.')
    }
  }

  function toggleDispenseForm(transactionType) {
    const isOpenForType =
      showDispenseForm && dispenseForm.transactionType === transactionType
    setShowDispenseForm(!isOpenForType)
    setDispenseForm({ ...emptyDispense, transactionType })
    setDispenseError('')
  }

  useEffect(() => {
    if (activePage !== 'Reports' || !reportBranchId) return
    let cancelled = false
    const params = new URLSearchParams({
      branchId: reportBranchId,
      start: reportStart,
      end: reportEnd,
    })
    apiRequest(`/api/reports/analytics/?${params}`)
      .then((data) => {
        if (!cancelled) {
          setAnalytics({ ...data, branchId: reportBranchId })
          setWorkflowError('')
        }
      })
      .catch((error) => {
        if (!cancelled) {
          if (isNetworkError(error)) setIsOnline(false)
          setWorkflowError(error.message || 'Could not load analytics.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [activePage, reportBranchId, reportStart, reportEnd])

  useEffect(() => {
    if (activePage !== 'Purchasing' || !activeBranchId) return
    let cancelled = false
    const params = new URLSearchParams({ branchId: activeBranchId })
    apiRequest(`/api/reports/replenishment/?${params}`)
      .then((data) => {
        if (!cancelled) setReplenishmentForecast(data)
      })
      .catch((error) => {
        if (!cancelled) {
          if (isNetworkError(error)) setIsOnline(false)
          setWorkflowError(error.message || 'Could not load replenishment forecasts.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [activePage, activeBranchId])

  useEffect(() => {
    let cancelled = false

    async function restoreSession() {
      try {
        const response = await fetch('/api/auth/me/', {
          credentials: 'include',
        })

        if (response.status === 401) {
          sessionStorage.removeItem('wellnest-session')
          return
        }

        const data = await response.json()
        if (!response.ok) {
          throw new Error(data.detail || 'Could not check your sign-in.')
        }

        if (!cancelled) {
          setCurrentUser(data.user)
          if (!saveCachedUser(data.user)) {
            setAuthError('Sign-in succeeded, but offline session storage is unavailable.')
          }
        }
      } catch (error) {
        if (!cancelled && isNetworkError(error)) {
          const cachedSession = readCachedSession()
          if (cachedSession?.user) {
            setCurrentUser(cachedSession.user)
            setBranches(cachedSession.branches || [])
            const homeBranchId = cachedSession.user.memberships?.find((membership) =>
              cachedSession.branches?.some(
                (branch) => String(branch.id) === String(membership.branchId),
              ),
            )?.branchId
            setActiveBranchId(String(homeBranchId ?? ''))
            setAnalyticsBranchId(String(cachedSession.branches?.[0]?.id ?? ''))
            if (
              cachedSession.user.isSuperuser &&
              cachedSession.user.memberships?.length === 0
            ) {
              setActivePage('Reports')
            }
            setIsOnline(false)
            setWorkflowNotice('Offline mode: continuing the previously signed-in browser session. New sign-ins require a connection.')
          } else {
            setAuthError('Could not reach the server. Sign in while connected once before using offline mode.')
          }
        } else if (!cancelled) {
          setAuthError(error.message || 'Could not check your sign-in.')
        }
      } finally {
        if (!cancelled) setAuthLoading(false)
      }
    }

    restoreSession()
    return () => {
      cancelled = true
    }
  }, [])

  async function handleLogin(event) {
    event.preventDefault()
    setAuthError('')
    setLoginSubmitting(true)

    try {
      const csrfResponse = await fetch('/api/auth/csrf/', {
        credentials: 'include',
      })
      const csrfData = await csrfResponse.json()

      if (!csrfResponse.ok) {
        throw new Error(csrfData.detail || 'Could not prepare secure sign-in.')
      }

      const response = await fetch('/api/auth/login/', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfData.csrfToken,
        },
        body: JSON.stringify({
          username: loginUsername,
          password: loginPassword,
        }),
      })
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || 'Sign-in failed.')
      }

      setCurrentUser(data.user)
      if (!saveCachedUser(data.user)) {
        setAuthError('Sign-in succeeded, but offline session storage is unavailable.')
      }
      setLoginPassword('')
    } catch (error) {
      setAuthError(error.message || 'Sign-in failed. Please try again.')
    } finally {
      setLoginSubmitting(false)
    }
  }

  async function handleLogout() {
    if (offlineDrafts.some((draft) => draft.status === 'pending')) {
      setAuthError('Sync or remove pending POS drafts before signing out. Drafts that need review will remain stored for this user.')
      return
    }
    setAuthError('')

    try {
      const csrfResponse = await fetch('/api/auth/csrf/', {
        credentials: 'include',
      })
      const csrfData = await csrfResponse.json()

      const response = await fetch('/api/auth/logout/', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'X-CSRFToken': csrfData.csrfToken,
        },
      })
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || 'Sign-out failed.')
      }

      const ownerKey = getOfflineOwnerKey(currentUser)
      sessionStorage.removeItem('wellnest-session')
      for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
        const key = sessionStorage.key(index)
        if (key?.startsWith(`wellnest-branch:${ownerKey}:`)) {
          sessionStorage.removeItem(key)
        }
      }
      window.location.reload()
    } catch (error) {
      setAuthError(error.message || 'Sign-out failed. Please try again.')
    }
  }

  const totalProducts = new Set(
    inventory.map((medicine) => medicine.sku)
  ).size

  const lowStockCount = inventory.filter(
    (medicine) => getStockStatus(medicine, today) === 'Low stock'
  ).length

  const outOfStockCount = inventory.filter(
    (medicine) => getStockStatus(medicine, today) === 'Out of stock'
  ).length

  const expiredCount = inventory.filter(
    (medicine) =>
      medicine.quantity > 0 && getStockStatus(medicine, today) === 'Expired'
  ).length

  const expiringSoonCount = inventory.filter((medicine) => {
    if (!medicine.expiry) return false
    const expiryDate = new Date(`${medicine.expiry}T00:00:00`)
    const daysUntilExpiry = Math.ceil(
      (expiryDate - today) / (1000 * 60 * 60 * 24)
    )

    return (
      medicine.quantity > 0 &&
      daysUntilExpiry >= 0 &&
      daysUntilExpiry <= 90
    )
  }).length

  const filteredMedicines = inventory.filter((medicine) => {
    const searchableText =
      `${medicine.name} ${medicine.category} ${medicine.sku} ${medicine.batch}`.toLowerCase()

    const matchesSearch = searchableText.includes(
      searchTerm.trim().toLowerCase()
    )
    const matchesStatus =
      statusFilter === 'all' || getStockStatus(medicine, today) === statusFilter

    return matchesSearch && matchesStatus
  })

  const selectedPrescriptionOption = prescriptionDispenseForm.lineKey
    .split(':')
  const selectedPrescription = prescriptions.find(
    (item) => String(item.id) === selectedPrescriptionOption[0],
  )
  const selectedPrescriptionLine = selectedPrescription?.lines.find(
    (item) => String(item.id) === selectedPrescriptionOption[1],
  )
  const selectedBatchProduct = products.find(
    (item) => item.sku === newBatch.sku.trim(),
  )
  const selectedCountBatch = inventory.find((item) => item.batch === stockCountForm.batch)
  const selectedReceiptOrder = purchaseOrders.find(
    (item) => String(item.id) === purchaseReceiptForm.orderId,
  )
  const selectedReceiptLine = selectedReceiptOrder?.lines.find(
    (item) => String(item.id) === purchaseReceiptForm.lineId,
  )
  const selectedTransferProduct = products.find((item) => item.sku === transferForm.sku)
  const canManageBranch = currentUser?.memberships.some(
      (membership) =>
        String(membership.branchId) === String(activeBranchId) &&
        membership.role === 'branch_manager',
    )
  const activeRole = currentUser?.memberships.find(
    (membership) => String(membership.branchId) === String(activeBranchId),
  )?.role
  const isCashier = activeRole === 'cashier'
  const canClinical = ['pharmacist', 'branch_manager'].includes(activeRole)
  const canViewFinancials = canManageBranch || currentUser?.isSuperuser
  const isCrossBranchAnalytics =
    Boolean(currentUser?.isSuperuser) &&
    String(reportBranchId) !== String(activeBranchId)
  const dispenseQuantity = Number(dispenseForm.quantity)
  const estimatedSale = dispenseForm.transactionType === 'Sale' &&
    Number.isInteger(dispenseQuantity) &&
    dispenseQuantity > 0
    ? getSaleAllocation(inventory, dispenseForm.sku, dispenseQuantity, today)
    : null

  function handleFormChange(event) {
    const { name, value } = event.target
    setNewBatch((current) => ({ ...current, [name]: value }))
  }

  function handleDispenseFormChange(event) {
    const { name, value } = event.target
    setDispenseForm((current) => ({ ...current, [name]: value }))
  }

  function handleStockCountFormChange(event) {
    const { name, value } = event.target
    setStockCountForm((current) => ({ ...current, [name]: value }))
  }

  async function handleAddBatch(event) {
    event.preventDefault()

    const batchNumber = newBatch.batch.trim()

    if (
      inventory.some(
        (item) => item.batch.toLowerCase() === batchNumber.toLowerCase()
      )
    ) {
      setFormError('That batch number is already in the inventory.')
      return
    }

    const quantity = Number(newBatch.quantity)
    const reorderLevel = Number(newBatch.reorderLevel)
    const purchaseCost = Number(newBatch.purchaseCost)
    const sellingPrice = Number(newBatch.sellingPrice)
    const sku = newBatch.sku.trim()
    const name = newBatch.name.trim()
    const supplier = newBatch.supplier.trim()

    try {
      await saveBranchAction('/api/batches/', {
        sku,
        name,
        category: newBatch.category.trim(),
        batch: batchNumber,
        quantity,
        reorderLevel,
        expiry: newBatch.expiry,
        supplier,
        purchaseCost,
        sellingPrice,
        witnessId: newBatch.witnessId || null,
      })
      setNewBatch(emptyBatch)
      setFormError('')
      setShowAddForm(false)
    } catch (error) {
      setFormError(error.message || 'Could not save this batch.')
    }
  }

  async function handleDispense(event) {
    event.preventDefault()

    const quantity = Number(dispenseForm.quantity)
    const transactionType = dispenseForm.transactionType
    const amountInput = dispenseForm.amountReceived.trim()
    const paymentMethod = dispenseForm.paymentMethod
    const recipient = dispenseForm.recipient.trim()

    if (
      !Number.isInteger(quantity) ||
      quantity <= 0 ||
      (transactionType !== 'Sale' && !recipient)
    ) {
      setDispenseError(
        transactionType === 'Sale'
          ? 'Enter a valid product and quantity.'
          : 'Enter a valid quantity and recipient.',
      )
      return
    }

    const canQueueOffline = transactionType === 'Sale' && isCashier
    if (!isOnline && !canQueueOffline) {
      setDispenseError('Only ordinary cashier POS sales can be queued offline. Stock adjustments and clinical dispensing require a connection.')
      return
    }

    const dispenseDate = new Date()
    dispenseDate.setHours(0, 0, 0, 0)

    const allocation = getSaleAllocation(
      inventory,
      dispenseForm.sku,
      quantity,
      dispenseDate,
    )

    if (isOnline && quantity > allocation.availableQuantity) {
      setDispenseError(
        `Only ${allocation.availableQuantity} units are available in non-expired batches.`
      )
      return
    }

    const amountReceived = amountInput === ''
      ? paymentMethod === 'Credit' ? 0 : allocation.saleAmount
      : Number(amountInput)

    if (
      transactionType === 'Sale' &&
      (!paymentMethod ||
        !Number.isFinite(amountReceived) ||
        amountReceived < 0 ||
        (isOnline && amountReceived > allocation.saleAmount) ||
        (amountInput === '' &&
          allocation.remaining > 0 &&
          paymentMethod !== 'Credit'))
    ) {
      setDispenseError(
        amountInput === '' && allocation.remaining > 0
          ? 'The total is unavailable from cached stock. Enter the amount received or select Credit.'
          : isOnline
            ? `Enter an amount received from 0 to ${allocation.saleAmount}.`
            : 'Enter a valid non-negative amount received.'
      )
      return
    }

    const clientRequestId = canQueueOffline ? crypto.randomUUID() : undefined
    const payload = {
      branchId: Number(activeBranchId),
      sku: dispenseForm.sku,
      transactionType,
      quantity,
      ...(transactionType === 'Non-sale issue' ? { recipient } : {}),
      amountReceived,
      paymentMethod,
      ...(transactionType === 'Sale' && dispenseForm.receiptEmail.trim()
        ? { receiptEmail: dispenseForm.receiptEmail.trim() }
        : {}),
      ...(clientRequestId ? { clientRequestId } : {}),
    }

    async function queueCashierSale(draftPayload, requestId) {
      const ownerKey = getOfflineOwnerKey(currentUser)
      const draft = {
        id: requestId,
        ownerKey,
        branchId: activeBranchId,
        createdAt: new Date().toISOString(),
        status: 'pending',
        payload: draftPayload,
        error: '',
      }
      await saveOfflineDraft(draft)
      const queuedDrafts = await getOfflineDrafts(ownerKey)
      setOfflineDrafts(queuedDrafts.sort((first, second) => first.createdAt.localeCompare(second.createdAt)))
      setDispenseForm(emptyDispense)
      setDispenseError('')
      setShowDispenseForm(false)
      setReceiptSaleId('')
      setWorkflowNotice('POS draft saved on this device. The server will validate and record the sale when the connection returns.')
    }

    if (!isOnline && canQueueOffline) {
      try {
        await queueCashierSale(payload, clientRequestId)
      } catch (error) {
        setDispenseError(error.message || 'Could not save this POS draft on the device.')
      }
      return
    }

    let saleResponse
    try {
      saleResponse = await apiRequest('/api/dispense/', {
        method: 'POST',
        body: payload,
      })
      payload.reference = saleResponse.sale?.reference || saleResponse.reference
    } catch (error) {
      if (canQueueOffline && isNetworkError(error)) {
        setIsOnline(false)
        try {
          await queueCashierSale(payload, clientRequestId)
        } catch (queueError) {
          setDispenseError(queueError.message || 'The server could not be reached and this POS draft could not be saved.')
        }
        return
      }
      setPrescriptionRedirectSku(
        error.code === 'prescription_required' ? dispenseForm.sku : ''
      )
      setDispenseError(error.message || 'Could not record this dispensing.')
      return
    }

    try {
      await refreshBranchData(activeBranchId)
      setDataError('')
    } catch (error) {
      if (isNetworkError(error)) {
        setIsOnline(false)
        setWorkflowNotice('The sale was submitted successfully. Branch data could not be refreshed and may be stale until reconnection.')
      } else {
        setWorkflowError(error.message || 'The sale was submitted, but branch data could not be refreshed.')
      }
    }

    setDispenseForm(emptyDispense)
    setDispenseError('')
    setPrescriptionRedirectSku('')
    setShowDispenseForm(false)
    setReceiptSaleId(transactionType === 'Sale' ? saleResponse?.sale?.id || '' : '')
    setWorkflowNotice(
      transactionType === 'Sale'
        ? `Sale ${payload.reference} recorded and stock updated.${saleResponse?.receiptEmailQueued ? ' Receipt email queued.' : ''}`
        : `Stock issue ${payload.reference} recorded.`,
    )
  }



  function handleSupplierInvoiceChange(event) {
    const { name } = event.target
    const value = event.target.type === 'file'
      ? event.target.files?.[0] || null
      : event.target.value
    setSupplierInvoiceForm((current) => {
      if (name === 'purchaseOrderId' && value) {
        const order = purchaseOrders.find((item) => String(item.id) === value)
        if (order) {
          return {
            ...current,
            purchaseOrderId: value,
            supplier: String(order.supplierId),
          }
        }
      }
      return { ...current, [name]: value }
    })
  }

  function handleSupplierPaymentChange(event) {
    const { name, value } = event.target
    setSupplierPaymentForm((current) => ({ ...current, [name]: value }))
  }

  async function handleSaveSupplierInvoice(event) {
    event.preventDefault()

    const supplierRecord = suppliers.find(
      (item) => String(item.id) === supplierInvoiceForm.supplier,
    )
    const supplier = supplierRecord?.name || ''
    const invoiceNumber = supplierInvoiceForm.invoiceNumber.trim()
    const invoiceAmount = Number(supplierInvoiceForm.invoiceAmount)
    const amountPaid = Number(supplierInvoiceForm.amountPaid)

    if (
      !supplier ||
      !invoiceNumber ||
      !supplierInvoiceForm.dueDate ||
      !Number.isFinite(invoiceAmount) ||
      invoiceAmount <= 0 ||
      !Number.isFinite(amountPaid) ||
      amountPaid < 0 ||
      amountPaid > invoiceAmount
    ) {
      setSupplierInvoiceError('Enter invoice details and valid amounts. Amount paid cannot exceed the invoice total.')
      return
    }

    if (supplierInvoices.some((invoice) => invoice.invoiceNumber.toLowerCase() === invoiceNumber.toLowerCase())) {
      setSupplierInvoiceError('That invoice number has already been entered.')
      return
    }

    try {
      const invoiceData = new FormData()
      invoiceData.set('supplier', supplier)
      invoiceData.set('supplierId', String(supplierRecord.id))
      invoiceData.set('invoiceNumber', invoiceNumber)
      invoiceData.set('invoiceAmount', String(invoiceAmount))
      invoiceData.set('amountPaid', String(amountPaid))
      invoiceData.set('dueDate', supplierInvoiceForm.dueDate)
      invoiceData.set('purchaseOrderId', supplierInvoiceForm.purchaseOrderId)
      invoiceData.set('method', 'Opening payment')
      if (supplierInvoiceForm.originalDocument) {
        invoiceData.set('originalDocument', supplierInvoiceForm.originalDocument)
      }
      const response = await saveBranchAction('/api/supplier-invoices/', invoiceData)
      setSupplierInvoiceForm(emptySupplierInvoice)
      if (supplierInvoiceDocumentRef.current) {
        supplierInvoiceDocumentRef.current.value = ''
      }
      setSupplierInvoiceError('')
      setShowSupplierInvoiceForm(false)
      setWorkflowNotice(
        `Supplier invoice ${response.invoice.reference} recorded. Keep the supplier's invoice number (${invoiceNumber}) for reconciliation.`,
      )
    } catch (error) {
      setSupplierInvoiceError(error.message || 'Could not save the supplier invoice.')
    }
  }

  async function handleRecordSupplierPayment(event) {
    event.preventDefault()

    const amount = Number(supplierPaymentForm.amount)
    const invoice = supplierInvoices.find((item) => item.id === supplierPaymentForm.invoiceId)

    if (!invoice || !supplierPaymentForm.method || !Number.isFinite(amount) || amount <= 0) {
      setSupplierPaymentError('Select an invoice and enter a valid payment and method.')
      return
    }

    const balance = invoice.invoiceAmount - invoice.amountPaid
    if (amount > balance) {
      setSupplierPaymentError(`Payment cannot exceed the remaining balance of ${balance.toLocaleString()}.`)
      return
    }

    try {
      const response = await saveBranchAction(`/api/supplier-invoices/${invoice.id}/payments/`, {
        amount,
        method: supplierPaymentForm.method,
      })
      setSupplierPaymentForm(emptySupplierPayment)
      setSupplierPaymentError('')
      setShowSupplierPaymentForm(false)
      setWorkflowNotice(`Supplier payment ${response.reference} recorded.`)
    } catch (error) {
      setSupplierPaymentError(error.message || 'Could not record the supplier payment.')
    }
  }

  async function handleReconcileSupplierInvoice(invoiceId) {
    setWorkflowError('')
    try {
      await saveBranchAction(`/api/supplier-invoices/${invoiceId}/reconcile/`, {})
    } catch (error) {
      setWorkflowError(error.message || 'Could not reconcile the supplier invoice.')
    }
  }

  function handleCustomerPaymentChange(event) {
    const { name, value } = event.target
    setCustomerPaymentForm((current) => ({ ...current, [name]: value }))
  }

  async function handleRecordCustomerPayment(event) {
    event.preventDefault()

    const sale = sales.find((item) => item.id === customerPaymentForm.saleId)
    const amount = Number(customerPaymentForm.amount)
    const method = customerPaymentForm.method

    if (!sale || !method || !Number.isFinite(amount) || amount <= 0) {
      setCustomerPaymentError('Select an outstanding sale and enter a valid payment and method.')
      return
    }

    if (amount > sale.balanceDue) {
      setCustomerPaymentError(`Payment cannot exceed the outstanding balance of ${sale.balanceDue.toLocaleString()}.`)
      return
    }

    try {
      const response = await saveBranchAction(`/api/sales/${sale.id}/payments/`, {
        amount,
        method,
      })
      setCustomerPaymentForm(emptyCustomerPayment)
      setCustomerPaymentError('')
      setShowCustomerPaymentForm(false)
      setWorkflowNotice(`Customer payment ${response.reference} recorded.`)
    } catch (error) {
      setCustomerPaymentError(error.message || 'Could not record the customer payment.')
    }
  }

  async function handleApproveSale(saleId) {
    setWorkflowError('')
    setWorkflowNotice('')
    try {
      await saveBranchAction(`/api/sales/${saleId}/approve/`, {})
      setWorkflowNotice('Sale approved, stock deducted, and payment recorded.')
    } catch (error) {
      setWorkflowError(error.message || 'Could not approve this sale.')
    }
  }

  async function handleRejectSale(saleId) {
    const reason = (saleRejectionReasons[saleId] || '').trim()
    if (!reason) {
      setWorkflowError('Enter a reason before rejecting a sale.')
      return
    }
    setWorkflowError('')
    setWorkflowNotice('')
    try {
      await saveBranchAction(`/api/sales/${saleId}/reject/`, { reason })
      setSaleRejectionReasons((current) => ({ ...current, [saleId]: '' }))
      setWorkflowNotice('Sale rejected. No stock or payment was recorded.')
    } catch (error) {
      setWorkflowError(error.message || 'Could not reject this sale.')
    }
  }

  async function handleStockCount(event) {
    event.preventDefault()

    const countedQuantity = Number(stockCountForm.quantity)
    const reason = stockCountForm.reason

    if (
      !stockCountForm.batch ||
      !Number.isInteger(countedQuantity) ||
      countedQuantity < 0 ||
      !reason
    ) {
      setStockCountError(
        'Select a batch, enter a whole-number count of zero or more, and provide a reason.'
      )
      return
    }

    const countedBatch = inventory.find(
      (item) => item.batch === stockCountForm.batch
    )

    if (!countedBatch) {
      setStockCountError('The selected batch could not be found.')
      return
    }

    const difference = countedQuantity - countedBatch.quantity

    if (difference === 0) {
      setStockCountError(
        'The counted quantity matches the recorded quantity. No adjustment is needed.'
      )
      return
    }

    try {
      const response = await saveBranchAction('/api/stock-count/', {
        batch: countedBatch.batch,
        quantity: countedQuantity,
        reason,
        witnessId: stockCountForm.witnessId || null,
      })
      setStockCountForm(emptyStockCount)
      setStockCountError('')
      setShowStockCountForm(false)
      setWorkflowNotice(`Stock count adjustment ${response.reference} recorded.`)
    } catch (error) {
      setStockCountError(error.message || 'Could not save the stock count.')
    }
  }

  async function handleCreatePrescription(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      await saveBranchAction('/api/prescriptions/create/', {
        ...prescriptionForm,
        branchId: Number(activeBranchId),
        lines: [{
          sku: prescriptionForm.sku,
          quantity: Number(prescriptionForm.quantity),
          directions: prescriptionForm.directions,
        }],
      })
      setPrescriptionForm(emptyPrescription)
    } catch (error) {
      setWorkflowError(error.message || 'Could not save the prescription.')
    }
  }

  async function handleVerifyPrescription(prescriptionId) {
    setWorkflowError('')
    try {
      await saveBranchAction(`/api/prescriptions/${prescriptionId}/verify/`, {})
    } catch (error) {
      setWorkflowError(error.message || 'Could not verify prescription.')
    }
  }

  async function handlePrescriptionDispense(event) {
    event.preventDefault()
    const [prescriptionId, lineId] = prescriptionDispenseForm.lineKey.split(':')
    const prescription = prescriptions.find((item) => String(item.id) === prescriptionId)
    if (!prescription || !lineId) {
      setWorkflowError('Select a verified prescription item to dispense.')
      return
    }
    const line = prescription.lines.find((item) => String(item.id) === lineId)
    setWorkflowError('')
    try {
      const response = await saveBranchAction(`/api/prescriptions/${prescription.id}/dispense/`, {
        branchId: Number(activeBranchId),
        lineId: Number(lineId),
        quantity: Number(prescriptionDispenseForm.quantity),
        amountReceived: Number(prescriptionDispenseForm.amountReceived),
        paymentMethod: prescriptionDispenseForm.paymentMethod,
        witnessId: prescriptionDispenseForm.witnessId || null,
      })
      setPrescriptionDispenseForm(emptyPrescriptionDispense)
      setReceiptSaleId(response.sale.id)
      setWorkflowNotice(`Prescription sale ${response.sale.reference} recorded.`)
    } catch (error) {
      setWorkflowError(error.message || `Could not dispense ${line?.name || 'prescription item'}.`)
    }
  }

  async function handleCreatePurchaseOrder(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      const response = await saveBranchAction('/api/purchase-orders/create/', {
        ...purchaseOrderForm,
        supplierId: Number(purchaseOrderForm.supplierId),
        branchId: Number(activeBranchId),
        lines: [{
          sku: purchaseOrderForm.sku,
          quantity: Number(purchaseOrderForm.quantity),
          unitCost: Number(purchaseOrderForm.unitCost),
        }],
      })
      setPurchaseOrderForm(emptyPurchaseOrder)
      setWorkflowNotice(`Purchase order ${response.number} created.`)
    } catch (error) {
      setWorkflowError(error.message || 'Could not create purchase order.')
    }
  }

  function handleUseForecast(item) {
    setPurchaseOrderForm({
      supplierId: String(item.supplierId),
      expectedDate: item.expectedDeliveryDate,
      sku: item.sku,
      quantity: String(item.suggestedOrderQuantity),
      unitCost: String(item.unitCost),
    })
    setWorkflowNotice(`Forecast for ${item.sku} loaded into the purchase-order form. Review supplier, quantity, cost, and delivery date before submitting.`)
  }

  async function handleCreateReorderDraft(sku) {
    setWorkflowError('')
    try {
      await saveBranchAction('/api/purchase-orders/reorder-draft/', {
        branchId: Number(activeBranchId),
        sku,
      })
    } catch (error) {
      setWorkflowError(error.message || 'Could not create a reorder draft.')
    }
  }

  async function handleSubmitPurchaseOrder(orderId) {
    setWorkflowError('')
    try {
      const response = await saveBranchAction(`/api/purchase-orders/${orderId}/submit/`, {
        branchId: Number(activeBranchId),
      })
      if (response.emailQueued) {
        setWorkflowNotice('Purchase order submitted; supplier email queued for delivery.')
      } else {
        setWorkflowNotice('Purchase order submitted. No supplier email is configured.')
      }
    } catch (error) {
      setWorkflowError(error.message || 'Could not submit purchase order.')
    }
  }

  async function handleReceivePurchaseOrder(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      await saveBranchAction(`/api/purchase-orders/${purchaseReceiptForm.orderId}/receive/`, {
        branchId: Number(activeBranchId),
        receipts: [{
          lineId: Number(purchaseReceiptForm.lineId),
          quantity: Number(purchaseReceiptForm.quantity),
          batch: purchaseReceiptForm.batch,
          expiry: purchaseReceiptForm.expiry,
          sellingPrice: Number(purchaseReceiptForm.sellingPrice),
          witnessId: purchaseReceiptForm.witnessId || null,
        }],
      })
      setPurchaseReceiptForm(emptyPurchaseReceipt)
    } catch (error) {
      setWorkflowError(error.message || 'Could not receive purchase order.')
    }
  }

  async function handleCreateTransfer(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      const response = await saveBranchAction('/api/transfers/create/', {
        sourceBranchId: Number(activeBranchId),
        destinationBranchId: Number(transferForm.destinationBranchId),
        lines: [{
          sku: transferForm.sku,
          quantity: Number(transferForm.quantity),
        }],
        witnessId: transferForm.witnessId || null,
      })
      setTransferWitnessId(transferForm.witnessId)
      setTransferForm(emptyTransfer)
      setWorkflowNotice(`Transfer ${response.reference} requested.`)
    } catch (error) {
      setWorkflowError(error.message || 'Could not request branch transfer.')
    }
  }

  async function handleTransferAction(transferId, action, branchId = activeBranchId) {
    setWorkflowError('')
    try {
      const transfer = transfers.find((item) => item.id === transferId)
      await saveBranchAction(`/api/transfers/${transferId}/${action}/`, {
        branchId: Number(branchId),
        witnessId: transferWitnessId || null,
        ...(action === 'receive' && transfer
          ? {
              quantities: Object.fromEntries(transfer.lines
                .filter((line) => line.quantityOutstanding > 0)
                .map((line) => [
                  String(line.id),
                  Number(transferReceiptQuantities[line.id] ?? line.quantityOutstanding),
                ])),
              batches: Object.fromEntries(transfer.lines
                .filter((line) => line.quantityOutstanding > 0)
                .map((line) => [
                  String(line.id),
                  transferReceiptBatches[line.id] || line.destinationBatch || line.batch,
                ])),
            }
          : {}),
      })
      if (action === 'receive') {
        setTransferReceiptQuantities({})
        setTransferReceiptBatches({})
      }
    } catch (error) {
      setWorkflowError(error.message || `Could not ${action} transfer.`)
    }
  }

  async function handleAnalyticsExport() {
    try {
      const params = new URLSearchParams({
        branchId: reportBranchId,
        start: reportStart,
        end: reportEnd,
      })
      const response = await fetch(`/api/reports/movements.csv?${params}`, {
        credentials: 'include',
      })
      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Could not export report.')
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'pharmacy-stock-movements.csv'
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      setWorkflowError(error.message || 'Could not export report.')
    }
  }

  async function handleRemoveOfflineDraft(draft) {
    try {
      await deleteOfflineDraft(draft.id)
      setOfflineDrafts((drafts) => drafts.filter((item) => item.id !== draft.id))
      setWorkflowNotice('Queued POS draft removed from this device.')
    } catch (error) {
      setWorkflowError(error.message || 'Could not remove the queued POS draft.')
    }
  }

  async function handleRetryConnection() {
    try {
      const response = await fetch('/api/auth/me/', { credentials: 'include' })
      if (!response.ok) {
        setAuthError('The server is reachable, but your sign-in may have expired. Reconnect and sign in again.')
        return
      }
      setIsOnline(true)
      setDataError('')
      setWorkflowError('')
    } catch (error) {
      setWorkflowNotice(error.message || 'The server is still unreachable. Your queued POS drafts remain on this device.')
    }
  }

  async function handleCreateProduct(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      const response = await apiRequest('/api/products/create/', {
        method: 'POST',
        body: productForm,
      })
      setProductForm(emptyProduct)
      await refreshBranchData()
      setWorkflowNotice(`Product created with SKU ${response.sku}.`)
    } catch (error) {
      setWorkflowError(error.message || 'Could not create product.')
    }
  }

  async function handleCreateSupplier(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      const response = await apiRequest('/api/suppliers/create/', {
        method: 'POST',
        body: supplierForm,
      })
      setSupplierForm(emptySupplier)
      await refreshBranchData()
      setWorkflowNotice(`Supplier ${response.reference} created.`)
    } catch (error) {
      setWorkflowError(error.message || 'Could not create supplier.')
    }
  }

  async function handleSetSupplierProduct(event) {
    event.preventDefault()
    setWorkflowError('')
    try {
      await apiRequest('/api/supplier-products/', {
        method: 'POST',
        body: {
          ...supplierProductForm,
          supplierId: Number(supplierProductForm.supplierId),
          leadTimeDays: Number(supplierProductForm.leadTimeDays),
        },
      })
      setSupplierProductForm(emptySupplierProduct)
      await refreshBranchData()
    } catch (error) {
      setWorkflowError(error.message || 'Could not configure supplier product.')
    }
  }

  const navPages = [
    ...(activeRole ? ['Overview', 'Inventory'] : []),
    ...(isOnline && canClinical ? ['Prescriptions'] : []),
    ...(isOnline && canManageBranch ? ['Purchasing', 'Suppliers', 'Transfers'] : []),
    ...(isOnline && (canManageBranch || currentUser?.isSuperuser) ? ['Reports'] : []),
    ...(isOnline && currentUser?.isStaff && (currentUser.isSuperuser || !isCashier) ? ['Administration'] : []),
  ]

  if (authLoading) {
    return <main className="auth-page">Checking your sign-in…</main>
  }

  if (!currentUser) {
    return (
      <LoginScreen
        username={loginUsername}
        setUsername={setLoginUsername}
        password={loginPassword}
        setPassword={setLoginPassword}
        error={authError}
        isSubmitting={loginSubmitting}
        onSubmit={handleLogin}
      />
    )
  }

  return (
    <div
      className={`app-layout${isSidebarCollapsed ? ' sidebar-collapsed' : ''}`}
      data-theme={theme}
    >
      <aside className="sidebar">
        <h2 className="sidebar-brand">Wellnest</h2>

        <button
          className="sidebar-toggle"
          type="button"
          onClick={() => setIsSidebarCollapsed((collapsed) => !collapsed)}
          aria-label={isSidebarCollapsed ? 'Show navigation' : 'Hide navigation'}
          aria-expanded={!isSidebarCollapsed}
          aria-controls="primary-navigation"
          title={isSidebarCollapsed ? 'Show navigation' : 'Hide navigation'}
        >
          <span aria-hidden="true">{isSidebarCollapsed ? '›' : '‹'}</span>
        </button>

        <nav id="primary-navigation" aria-label="Main navigation">
          {navPages.map((page) => (
            <button
              key={page}
              type="button"
              className={activePage === page ? 'nav-link active' : 'nav-link'}
              onClick={() => setActivePage(page)}
              aria-current={activePage === page ? 'page' : undefined}
              title={page}
            >
              <span className="nav-icon" aria-hidden="true">{page[0]}</span>
              <span className="nav-label">{page}</span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <h1>
            {activePage === 'Overview' ? 'Pharmacy Inventory' : activePage}
          </h1>
          <div className="topbar-actions">
            <span className={isOnline ? 'connection-status online' : 'connection-status offline'} role="status">
              {isOnline ? 'Online' : 'Offline'}
            </span>
            {!isOnline && <button type="button" onClick={handleRetryConnection}>Retry connection</button>}
            {activeBranchId && (
              <span className="active-branch-label">
                Branch: {branches.find((branch) => String(branch.id) === String(activeBranchId))?.name || 'Assigned branch'}
              </span>
            )}
            {currentUser.isSuperuser && activePage === 'Reports' && branches.length > 1 && (
              <label className="branch-select">
                Analytics branch
                <select
                  value={analyticsBranchId}
                  onChange={(event) => setAnalyticsBranchId(event.target.value)}
                  aria-label="Analytics branch"
                >
                  {branches.map((branch) => (
                    <option key={branch.id} value={branch.id}>
                      {branch.code} — {branch.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {currentUser.isSuperuser &&
              activePage === 'Reports' &&
              branches.length === 1 &&
              String(activeBranchId) !== String(branches[0].id) && (
                <span className="active-branch-label">
                  Analytics branch: {branches[0].name}
                </span>
              )}
            <button
              className="theme-toggle"
              type="button"
              onClick={toggleTheme}
              aria-pressed={theme === 'dark'}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                {theme === 'dark' ? (
                  <path d="M12 3v2m0 14v2m9-9h-2M5 12H3m15.36-6.36-1.42 1.42M7.06 16.94l-1.42 1.42m12.72 0-1.42-1.42M7.06 7.06 5.64 5.64M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z" />
                ) : (
                  <path d="M20.3 15.3A8.5 8.5 0 0 1 8.7 3.7 8.5 8.5 0 1 0 20.3 15.3Z" />
                )}
              </svg>
            </button>
            <div className="account-actions">
              <span className="signed-in-user">
                Signed in as {currentUser.firstName || currentUser.username}
              </span>
              <button type="button" onClick={handleLogout}>
                Sign out
              </button>
            </div>
            {authError && <span className="auth-error" role="alert">{authError}</span>}
          </div>
        </header>

        <section className="dashboard">
          {dataError && <p className="form-error" role="alert">{dataError}</p>}
          {workflowError && <p className="form-error" role="alert">{workflowError}</p>}
          {workflowNotice && <p role="status">{workflowNotice}</p>}
          {receiptSaleId && (
            <p>
              <a
                className="receipt-pdf-link"
                href={`/api/sales/${receiptSaleId}/receipt.pdf`}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open/print sale receipt (PDF)
              </a>
            </p>
          )}
          {!isOnline && (
            <p className="offline-warning" role="status">
              Showing cached inventory where available. Cashiers may queue ordinary POS drafts; stock, payment, prescription, controlled-medicine, and approval actions require a connection.
            </p>
          )}
          {!dataError && branches.length === 0 && (
            <p className="form-error" role="alert">
              No active branch is assigned to your account. Ask an administrator to assign one.
            </p>
          )}
          {currentUser && activeBranchId && loadedBranchId !== activeBranchId && (
            <p role="status">Loading branch data…</p>
          )}
          {activePage === 'Overview' && (
            <>
              <h2>{timeGreeting}</h2>
              <p>Here’s an overview of your pharmacy stock.</p>
              <div className="summary-cards">
                <article className="summary-card">
                  <span>Total products</span>
                  <strong>{totalProducts}</strong>
                </article>

                <article className="summary-card">
                  <span>Low stock items</span>
                  <strong>{lowStockCount}</strong>
                </article>

                <article className="summary-card">
                  <span>Out of stock</span>
                  <strong>{outOfStockCount}</strong>
                </article>

                <article className="summary-card">
                  <span>Expiring within 90 days</span>
                  <strong>{expiringSoonCount}</strong>
                </article>

                <article className="summary-card">
                  <span>Expired stock</span>
                  <strong>{expiredCount}</strong>
                </article>
              </div>

              {offlineDrafts.length > 0 && (
                <section className="inventory-panel offline-queue">
                  <div className="inventory-heading">
                    <div>
                      <h2>Queued POS drafts</h2>
                      <p>These are not completed sales yet. The server validates and records each draft after reconnection; unresolved price or stock conflicts will need review.</p>
                    </div>
                  </div>
                  <table>
                    <thead><tr><th>Reference</th><th>Branch</th><th>Saved</th><th>Status</th><th>Action</th></tr></thead>
                    <tbody>
                      {offlineDrafts.map((draft) => (
                        <tr key={draft.id}>
                          <td>{draft.status === 'needs_review' ? 'Not recorded' : 'Assigned when synced'}</td>
                          <td>{draft.branchId}</td>
                          <td>{new Date(draft.createdAt).toLocaleString()}</td>
                          <td>{draft.status === 'needs_review' ? `Needs review: ${draft.error}` : 'Waiting to sync'}</td>
                          <td><button type="button" onClick={() => handleRemoveOfflineDraft(draft)}>Remove</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              )}

              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Reorder suggestions</h2>
                    <p>Products at or below their reorder level.</p>
                  </div>
                </div>

                <table>
                  <thead>
                    <tr>
                      <th>SKU</th>
                      <th>Medicine</th>
                      <th>Current stock</th>
                      <th>Reorder level</th>
                      <th>Suggested order</th>
                    </tr>
                  </thead>

                  <tbody>
                    {reorderSuggestions.map((product) => (
                      <tr key={product.sku}>
                        <td>{product.sku}</td>
                        <td>{product.name}</td>
                        <td>{product.totalQuantity}</td>
                        <td>{product.reorderLevel}</td>
                        <td>{product.suggestedOrder}</td>
                      </tr>
                    ))}

                    {reorderSuggestions.length === 0 && (
                      <tr>
                        <td colSpan="5">
                          No products currently need reordering.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </section>
            </>
          )}

          {activePage === 'Inventory' && (
            <section className="inventory-panel">
              <div className="inventory-heading">
                <div>
                  <h2>Medicine inventory</h2>
                  <p>Check current stock levels.</p>
                </div>

                <input
                  className="inventory-search"
                  type="search"
                  placeholder="Search medicines..."
                  aria-label="Search medicines"
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                />

                <select
                  className="inventory-filter"
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value)}
                  aria-label="Filter by stock status"
                >
                  <option value="all">All statuses</option>
                  <option value="In stock">In stock</option>
                  <option value="Low stock">Low stock</option>
                  <option value="Out of stock">Out of stock</option>
                  <option value="Expired">Expired</option>
                </select>

                {canClinical && <button
                  type="button"
                  onClick={() => setShowAddForm((shown) => !shown)}
                >
                  {showAddForm ? 'Close add form' : 'Add batch'}
                </button>}

                <button
                  type="button"
                  onClick={() => toggleDispenseForm('Sale')}
                >
                  {showDispenseForm && dispenseForm.transactionType === 'Sale'
                    ? 'Close sale'
                    : 'New sale'}
                </button>
                {canClinical && (
                  <button
                    className="button-secondary"
                    type="button"
                    onClick={() => toggleDispenseForm('Non-sale issue')}
                  >
                    {showDispenseForm && dispenseForm.transactionType === 'Non-sale issue'
                      ? 'Close stock issue'
                      : 'Record stock issue'}
                  </button>
                )}

                {canClinical && <button
                  type="button"
                  onClick={() => setShowStockCountForm((shown) => !shown)}
                >
                  {showStockCountForm ? 'Close stock count' : 'Stock count'}
                </button>}
              </div>

              {showAddForm && canClinical && (
                <form className="batch-form" onSubmit={handleAddBatch}>
                  <label>
                    SKU
                    <input
                      name="sku"
                      value={newBatch.sku}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Product
                    <input
                      name="name"
                      value={newBatch.name}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Category
                    <input
                      name="category"
                      value={newBatch.category}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Batch number
                    <input
                      name="batch"
                      value={newBatch.batch}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Quantity
                    <input
                      name="quantity"
                      type="number"
                      min="0"
                      step="1"
                      value={newBatch.quantity}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Reorder level
                    <input
                      name="reorderLevel"
                      type="number"
                      min="0"
                      step="1"
                      value={newBatch.reorderLevel}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Purchase cost per unit
                    <input
                      name="purchaseCost"
                      type="number"
                      min="0"
                      step="0.01"
                      value={newBatch.purchaseCost}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Selling price per unit
                    <input
                      name="sellingPrice"
                      type="number"
                      min="0"
                      step="0.01"
                      value={newBatch.sellingPrice}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  <label>
                    Expiry date (leave blank only when none is printed on the skincare package)
                    <input
                      name="expiry"
                      type="date"
                      value={newBatch.expiry}
                      onChange={handleFormChange}
                      required={selectedBatchProduct?.productType !== 'skin_care'}
                    />
                  </label>

                  <label>
                    Supplier / source
                    <input
                      name="supplier"
                      value={newBatch.supplier}
                      onChange={handleFormChange}
                      required
                    />
                  </label>

                  {selectedBatchProduct?.isControlled && (
                    <label>Independent witness
                      <select name="witnessId" value={newBatch.witnessId} onChange={handleFormChange} required>
                        <option value="">Select witness</option>
                        {branchStaff.filter((member) => member.id !== currentUser.id).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}
                      </select>
                    </label>
                  )}

                  {formError && <p className="form-error">{formError}</p>}

                  <button type="submit">Save batch</button>
                </form>
              )}

              {showDispenseForm && (
                <form className="batch-form" onSubmit={handleDispense}>
                  <label>
                    Product
                    <select
                      name="sku"
                      value={dispenseForm.sku}
                      onChange={handleDispenseFormChange}
                      required
                    >
                      <option value="">Select product</option>
                      {[
                        ...new Map(
                          inventory.map((item) => [item.sku, item])
                        ).values(),
                      ].map((medicine) => (
                        <option key={medicine.sku} value={medicine.sku}>
                          {medicine.name}{medicine.brand ? ` · ${medicine.brand}` : ''} ({medicine.productType === 'skin_care' ? 'Skin care' : 'Medicine'})
                        </option>
                      ))}
                    </select>
                  </label>

                  <label>
                    Quantity to dispense
                    <input
                      name="quantity"
                      type="number"
                      min="1"
                      step="1"
                      value={dispenseForm.quantity}
                      onChange={handleDispenseFormChange}
                      required
                    />
                  </label>

                  {dispenseForm.transactionType !== 'Sale' && <>
                    <label>
                      Issued to / reason
                      <input
                        name="recipient"
                        value={dispenseForm.recipient}
                        onChange={handleDispenseFormChange}
                        required
                      />
                    </label>
                  </>}


                  {dispenseForm.transactionType === 'Sale' && (
                    <>
                      <label>
                        Amount received
                        <input
                          name="amountReceived"
                          type="number"
                          min="0"
                          step="0.01"
                          value={dispenseForm.amountReceived}
                          onChange={handleDispenseFormChange}
                        />
                      </label>
                      {estimatedSale && estimatedSale.remaining === 0 && (
                        <p className="sale-total" role="status">
                          Sale total: {estimatedSale.saleAmount.toLocaleString()}
                        </p>
                      )}

                      <label>
                        Payment method
                        <select
                          name="paymentMethod"
                          value={dispenseForm.paymentMethod}
                          onChange={handleDispenseFormChange}
                          required
                        >
                          <option value="Cash">Cash</option>
                          <option value="Mobile money">Mobile money</option>
                          <option value="Bank transfer">Bank transfer</option>
                          <option value="Card">Card</option>
                          <option value="Credit">Credit</option>
                        </select>
                      </label>
                      <label>
                        Receipt email (optional)
                        <input
                          name="receiptEmail"
                          type="email"
                          value={dispenseForm.receiptEmail}
                          onChange={handleDispenseFormChange}
                        />
                      </label>
                    </>
                  )}
                  {dispenseError && (
                    <div className="form-error" role="alert">
                      <p>{dispenseError}</p>
                      {prescriptionRedirectSku && (
                        <button
                          type="button"
                          onClick={() => {
                            setPrescriptionForm((current) => ({
                              ...current,
                              sku: prescriptionRedirectSku,
                            }))
                            setPrescriptionRedirectSku('')
                            setDispenseError('')
                            setShowDispenseForm(false)
                            setWorkflowError('')
                            setActivePage('Prescriptions')
                          }}
                        >
                          Record prescription for this medicine
                        </button>
                      )}
                    </div>
                  )}

                  <button type="submit">
                    {dispenseForm.transactionType === 'Sale' ? 'Complete sale' : 'Record stock issue'}
                  </button>
                </form>
              )}

              {showStockCountForm && canClinical && (
                <form className="batch-form" onSubmit={handleStockCount}>
                  <label>
                    Batch to count
                    <select
                      name="batch"
                      value={stockCountForm.batch}
                      onChange={handleStockCountFormChange}
                      required
                    >
                      <option value="">Select a batch</option>
                      {inventory.map((medicine) => (
                        <option key={medicine.batch} value={medicine.batch}>
                          {medicine.name} — {medicine.batch} (recorded:{' '}
                          {medicine.quantity})
                        </option>
                      ))}
                    </select>
                  </label>

                  <label>
                    Quantity counted on shelf
                    <input
                      name="quantity"
                      type="number"
                      min="0"
                      step="1"
                      value={stockCountForm.quantity}
                      onChange={handleStockCountFormChange}
                      required
                    />
                  </label>

                  <label>
                    Reason for difference
                    <select
                      name="reason"
                      value={stockCountForm.reason}
                      onChange={handleStockCountFormChange}
                      required
                    >
                      <option value="">Select a reason</option>
                      <option value="Damaged stock">Damaged stock</option>
                      <option value="Expired stock">Expired stock</option>
                      <option value="Loss or theft">Loss or theft</option>
                      <option value="Counting correction">
                        Counting correction
                      </option>
                      <option value="Other">Other</option>
                    </select>
                  </label>

                  {selectedCountBatch?.isControlled && (
                    <label>Independent witness
                      <select name="witnessId" value={stockCountForm.witnessId} onChange={handleStockCountFormChange} required>
                        <option value="">Select witness</option>
                        {branchStaff.filter((member) => member.id !== currentUser.id).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}
                      </select>
                    </label>
                  )}

                  {stockCountError && (
                    <p className="form-error">{stockCountError}</p>
                  )}

                  <button type="submit">Save stock count</button>
                </form>
              )}

              <table>
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>Product</th>
                    <th>Type</th>
                    <th>Batch</th>
                    <th>Category</th>
                    <th>Quantity</th>
                    {canViewFinancials && <th>Purchase cost / unit</th>}
                    <th>Selling price / unit</th>
                    {canViewFinancials && <th>Gross profit / unit</th>}
                    <th>Expiry date</th>
                    <th>Status</th>
                  </tr>
                </thead>

                <tbody>
                  {filteredMedicines.map((medicine) => {
                    const status = getStockStatus(medicine, today)
                    const statusClass = {
                      'In stock': 'in-stock',
                      'Low stock': 'low-stock',
                      'Out of stock': 'out-of-stock',
                      Expired: 'expired',
                    }[status]

                    return (
                      <tr key={medicine.batch}>
                        <td>{medicine.sku}</td>
                        <td>{medicine.name}{medicine.brand ? ` · ${medicine.brand}` : ''}</td>
                        <td>{medicine.productType === 'skin_care' ? 'Skin care' : 'Medicine'}</td>
                        <td>{medicine.batch}</td>
                        <td>{medicine.category}</td>
                        <td>{medicine.quantity}</td>
                        {canViewFinancials && <td>{Number(medicine.purchaseCost || 0).toLocaleString()}</td>}
                        <td>{Number(medicine.sellingPrice || 0).toLocaleString()}</td>
                        {canViewFinancials && <td>{(Number(medicine.sellingPrice || 0) - Number(medicine.purchaseCost || 0)).toLocaleString()}</td>}
                        <td>{medicine.expiry || 'No printed expiry'}</td>
                        <td>
                          <span className={`stock-status ${statusClass}`}>
                            {status}
                          </span>
                        </td>
                      </tr>
                    )
                  })}

                  {filteredMedicines.length === 0 && (
                    <tr>
                      <td colSpan={canViewFinancials ? 11 : 9}>No matching batches found.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </section>
          )}
          {activePage === 'Prescriptions' && (
            <>
              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Prescription intake</h2>
                    <p>
                      Store a minimum patient reference and prescriber details.
                      Verify a prescription before dispensing.
                    </p>
                  </div>
                </div>
                <form className="batch-form" onSubmit={handleCreatePrescription}>
                  <label>Prescription reference
                    <input value={prescriptionForm.reference} onChange={(event) => setPrescriptionForm((current) => ({ ...current, reference: event.target.value }))} required />
                  </label>
                  <label>Patient reference (avoid full names)
                    <input value={prescriptionForm.patientReference} onChange={(event) => setPrescriptionForm((current) => ({ ...current, patientReference: event.target.value }))} required />
                  </label>
                  <label>Prescriber
                    <input value={prescriptionForm.prescriberName} onChange={(event) => setPrescriptionForm((current) => ({ ...current, prescriberName: event.target.value }))} required />
                  </label>
                  <label>Registration reference
                    <input value={prescriptionForm.prescriberRegistration} onChange={(event) => setPrescriptionForm((current) => ({ ...current, prescriberRegistration: event.target.value }))} />
                  </label>
                  <label>Issue date
                    <input type="date" value={prescriptionForm.issuedDate} onChange={(event) => setPrescriptionForm((current) => ({ ...current, issuedDate: event.target.value }))} required />
                  </label>
                  <label>Expiry date (if stated)
                    <input type="date" value={prescriptionForm.expiresDate} onChange={(event) => setPrescriptionForm((current) => ({ ...current, expiresDate: event.target.value }))} />
                  </label>
                  <label>Product
                    <select value={prescriptionForm.sku} onChange={(event) => setPrescriptionForm((current) => ({ ...current, sku: event.target.value }))} required>
                      <option value="">Select product</option>
                      {products.filter((product) => product.productType !== 'skin_care').map((product) => <option key={product.sku} value={product.sku}>{product.sku} — {product.name}{product.isControlled ? ' (controlled)' : product.requiresPrescription ? ' (prescription required)' : ''}</option>)}
                    </select>
                  </label>
                  <label>Quantity prescribed
                    <input type="number" min="1" step="1" value={prescriptionForm.quantity} onChange={(event) => setPrescriptionForm((current) => ({ ...current, quantity: event.target.value }))} required />
                  </label>
                  <label>Directions
                    <input value={prescriptionForm.directions} onChange={(event) => setPrescriptionForm((current) => ({ ...current, directions: event.target.value }))} />
                  </label>
                  <button type="submit">Save prescription</button>
                </form>
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Prescription queue</h2><p>Verify, dispense against prescribed quantities, and review history.</p></div></div>
                <table>
                  <thead><tr><th>Reference</th><th>Patient reference</th><th>Prescriber</th><th>Items</th><th>Status</th><th>Action</th></tr></thead>
                  <tbody>
                    {prescriptions.map((prescription) => <tr key={prescription.id}>
                      <td>{prescription.reference}</td><td>{prescription.patientReference}</td><td>{prescription.prescriberName}</td>
                      <td>{prescription.lines.map((line) => `${line.name}: ${line.quantityDispensed}/${line.quantityPrescribed}${line.isControlled ? ' (controlled)' : ''}`).join('; ')}</td>
                      <td>{prescription.status}</td>
                      <td>{prescription.status === 'received' && <button type="button" onClick={() => handleVerifyPrescription(prescription.id)}>Verify</button>}</td>
                    </tr>)}
                    {prescriptions.length === 0 && <tr><td colSpan="6">No prescriptions recorded for this branch.</td></tr>}
                  </tbody>
                </table>
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Dispense prescription item</h2><p>Unexpired lots are allocated FEFO; controlled items require a second branch member as witness.</p></div></div>
                <form className="batch-form" onSubmit={handlePrescriptionDispense}>
                  <label>Verified prescription item
                    <select value={prescriptionDispenseForm.lineKey} onChange={(event) => setPrescriptionDispenseForm((current) => ({ ...current, lineKey: event.target.value }))} required>
                      <option value="">Select an item</option>
                      {prescriptions.filter((item) => ['verified', 'partially_dispensed'].includes(item.status)).flatMap((prescription) => prescription.lines.filter((line) => line.quantityDispensed < line.quantityPrescribed).map((line) => <option key={`${prescription.id}:${line.id}`} value={`${prescription.id}:${line.id}`}>{prescription.reference} — {line.name} — remaining {line.quantityPrescribed - line.quantityDispensed}</option>))}
                    </select>
                  </label>
                  <label>Quantity
                    <input type="number" min="1" step="1" value={prescriptionDispenseForm.quantity} onChange={(event) => setPrescriptionDispenseForm((current) => ({ ...current, quantity: event.target.value }))} required />
                  </label>
                  <label>Amount received
                    <input type="number" min="0" step="0.01" value={prescriptionDispenseForm.amountReceived} onChange={(event) => setPrescriptionDispenseForm((current) => ({ ...current, amountReceived: event.target.value }))} required />
                  </label>
                  <label>Payment method
                    <select value={prescriptionDispenseForm.paymentMethod} onChange={(event) => setPrescriptionDispenseForm((current) => ({ ...current, paymentMethod: event.target.value }))} required>
                      <option value="">Select method</option><option>Cash</option><option>Mobile money</option><option>Bank transfer</option><option>Card</option><option>Credit</option>
                    </select>
                  </label>
                  <label>Dispense reference
                    <span className="generated-reference-note">Generated automatically when the item is dispensed.</span>
                  </label>
                  {selectedPrescriptionLine?.isControlled && <label>Independent witness
                    <select value={prescriptionDispenseForm.witnessId} onChange={(event) => setPrescriptionDispenseForm((current) => ({ ...current, witnessId: event.target.value }))} required>
                      <option value="">Select witness</option>
                      {branchStaff.filter((member) => member.id !== currentUser.id).map((member) => <option key={member.id} value={member.id}>{member.name} — {member.role}</option>)}
                    </select>
                  </label>}
                  {workflowError && <p className="form-error" role="alert">{workflowError}</p>}
                  <button type="submit">Dispense item</button>
                </form>
              </section>
            </>
          )}

          {activePage === 'Purchasing' && (
            <>
              {workflowError && <p className="form-error" role="alert">{workflowError}</p>}
              <section className="inventory-panel forecast-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Demand forecast assistant</h2>
                    <p>Local, explainable forecast from approved sales. Recommendations are advisory; no orders are created or submitted automatically.</p>
                  </div>
                </div>
                <p className="forecast-method">
                  Uses a 56-day weighted moving average (recent 28 days weighted 70%), supplier lead time plus a 14-day review buffer, configured reorder levels, and estimated near-expiry surplus. Stockout days are not adjusted for, so review low-confidence results.
                </p>
                {replenishmentForecast && String(replenishmentForecast.branchId) === String(activeBranchId) ? (
                  <table>
                    <thead>
                      <tr><th>Product</th><th>Demand/day</th><th>Confidence</th><th>Lead / horizon</th><th>Stock / target</th><th>Expiry exposure</th><th>Suggested order</th><th>Supplier</th><th>Why / action</th></tr>
                    </thead>
                    <tbody>
                      {replenishmentForecast.recommendations.map((item) => (
                        <tr key={item.sku}>
                          <td>{item.sku} — {item.name}</td>
                          <td>{item.averageDailyDemand} units<br />{item.salesDays}/{item.lookbackDays} sales days</td>
                          <td><span className={`forecast-confidence ${item.confidence}`}>{item.confidence}</span><br />{item.confidenceReason}</td>
                          <td>{item.leadTimeDays} / {item.forecastHorizonDays} days</td>
                          <td>{item.effectiveStock} / {item.targetStock} units</td>
                          <td>{item.expiringWithin30Days} units expiring; {item.estimatedExpiryRisk} estimated at risk</td>
                          <td><strong>{item.suggestedOrderQuantity}</strong></td>
                          <td>{item.supplier || 'Not configured'}</td>
                          <td>
                            <details>
                              <summary>Reasoning</summary>
                              <ul>{item.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                            </details>
                            {item.suggestedOrderQuantity > 0 && item.supplierId && item.unitCost !== null
                              ? <button type="button" onClick={() => handleUseForecast(item)}>Use in PO form</button>
                              : item.suggestedOrderQuantity > 0 ? 'Configure a preferred supplier' : 'No order suggested'}
                          </td>
                        </tr>
                      ))}
                      {!replenishmentForecast.recommendations.length && (
                        <tr><td colSpan="9">No active products with branch stock to forecast.</td></tr>
                      )}
                    </tbody>
                  </table>
                ) : <p role="status">Loading forecast…</p>}
              </section>
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Reorder recommendations</h2><p>Suggestions use unexpired on-hand quantities and configured batch reorder points.</p></div></div>
                <table>
                  <thead><tr><th>SKU</th><th>Product</th><th>Available</th><th>Reorder point</th><th>Suggested</th><th>Preferred supplier</th><th>Action</th></tr></thead>
                  <tbody>{reorderSuggestions.map((item) => <tr key={item.sku}>
                    <td>{item.sku}</td><td>{item.name}</td><td>{item.onHand}</td><td>{item.reorderLevel}</td><td>{item.suggestedQuantity}</td><td>{item.supplier || 'Not configured'}</td>
                    <td>{canManageBranch && item.supplierId
                      ? <button type="button" onClick={() => handleCreateReorderDraft(item.sku)}>Create draft PO</button>
                      : !item.supplierId ? 'Configure supplier mapping' : 'Manager permission required'}</td>
                  </tr>)}{!reorderSuggestions.length && <tr><td colSpan="7">No products currently need reordering.</td></tr>}</tbody>
                </table>
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Purchase order</h2><p>Create and submit an order; only branch managers can create or receive orders.</p></div></div>
                {canManageBranch ? <form className="batch-form" onSubmit={handleCreatePurchaseOrder}>
                  <label>Supplier<select value={purchaseOrderForm.supplierId} onChange={(event) => setPurchaseOrderForm((current) => ({ ...current, supplierId: event.target.value }))} required><option value="">Select supplier</option>{suppliers.map((item) => <option key={item.id} value={item.id}>{item.reference} — {item.name}</option>)}</select></label>
                  <label>Expected date<input type="date" value={purchaseOrderForm.expectedDate} onChange={(event) => setPurchaseOrderForm((current) => ({ ...current, expectedDate: event.target.value }))} /></label>
                  <label>Product<select value={purchaseOrderForm.sku} onChange={(event) => setPurchaseOrderForm((current) => ({ ...current, sku: event.target.value }))} required><option value="">Select product</option>{products.map((item) => <option key={item.sku} value={item.sku}>{item.sku} — {item.name}</option>)}</select></label>
                  <label>Quantity<input type="number" min="1" step="1" value={purchaseOrderForm.quantity} onChange={(event) => setPurchaseOrderForm((current) => ({ ...current, quantity: event.target.value }))} required /></label>
                  <label>Unit cost<input type="number" min="0" step="0.01" value={purchaseOrderForm.unitCost} onChange={(event) => setPurchaseOrderForm((current) => ({ ...current, unitCost: event.target.value }))} required /></label>
                  <button type="submit">Submit purchase order</button>
                </form> : <p className="form-error">Branch manager permission is required.</p>}
                {purchaseReceiptForm.orderId && <form className="batch-form" onSubmit={handleReceivePurchaseOrder}>
                  <h3>Receive against order {purchaseReceiptForm.orderId}</h3>
                  <label>Received quantity<input type="number" min="1" step="1" value={purchaseReceiptForm.quantity} onChange={(event) => setPurchaseReceiptForm((current) => ({ ...current, quantity: event.target.value }))} required /></label>
                  <label>Lot number<input value={purchaseReceiptForm.batch} onChange={(event) => setPurchaseReceiptForm((current) => ({ ...current, batch: event.target.value }))} required /></label>
                  <label>Expiry date<input type="date" value={purchaseReceiptForm.expiry} onChange={(event) => setPurchaseReceiptForm((current) => ({ ...current, expiry: event.target.value }))} required={selectedReceiptLine?.productType !== 'skin_care'} /></label>
                  <label>Retail price per unit<input type="number" min="0" step="0.01" value={purchaseReceiptForm.sellingPrice} onChange={(event) => setPurchaseReceiptForm((current) => ({ ...current, sellingPrice: event.target.value }))} required /></label>
                  {selectedReceiptLine?.isControlled && <label>Independent witness<select value={purchaseReceiptForm.witnessId} onChange={(event) => setPurchaseReceiptForm((current) => ({ ...current, witnessId: event.target.value }))} required><option value="">Select witness</option>{branchStaff.filter((member) => member.id !== currentUser.id).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label>}
                  <button type="submit">Receive stock</button>
                  <button type="button" onClick={() => setPurchaseReceiptForm(emptyPurchaseReceipt)}>Cancel</button>
                </form>}
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Purchase orders</h2><p>Record actual quantities, lots, expiry, and retail price when stock arrives.</p></div></div>
                <table><thead><tr><th>Order</th><th>Supplier</th><th>Product lines</th><th>Status</th><th>Actions</th></tr></thead><tbody>
                  {purchaseOrders.map((order) => <tr key={order.id}><td>{order.number}</td><td>{order.supplier}</td><td>{order.lines.map((line) => `${line.sku}: ${line.quantityReceived}/${line.quantityOrdered}`).join('; ')}</td><td>{order.status}</td><td>{canManageBranch && order.status === 'draft' && <button type="button" onClick={() => handleSubmitPurchaseOrder(order.id)}>Submit order</button>}{canManageBranch && ['submitted', 'partially_received'].includes(order.status) && order.lines.filter((line) => line.quantityReceived < line.quantityOrdered).map((line) => <button key={line.id} type="button" onClick={() => setPurchaseReceiptForm({ orderId: String(order.id), lineId: String(line.id), quantity: String(line.quantityOrdered - line.quantityReceived), batch: '', expiry: '', sellingPrice: '', witnessId: '' })}>Receive {line.sku}</button>)}</td></tr>)}
                  {!purchaseOrders.length && <tr><td colSpan="5">No purchase orders for this branch.</td></tr>}
                </tbody></table>
              </section>
            </>
          )}

          {activePage === 'Transfers' && (
            <>
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Request branch transfer</h2><p>Transfers require manager permissions at each branch. Stock moves on dispatch and is received into a destination lot.</p></div></div>
                {canManageBranch ? <form className="batch-form" onSubmit={handleCreateTransfer}>
                  <label>Destination branch<select value={transferForm.destinationBranchId} onChange={(event) => setTransferForm((current) => ({ ...current, destinationBranchId: event.target.value }))} required><option value="">Select branch</option>{branches.filter((item) => String(item.id) !== String(activeBranchId) && currentUser.memberships.some((membership) => String(membership.branchId) === String(item.id))).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                  <label>Product<select value={transferForm.sku} onChange={(event) => setTransferForm((current) => ({ ...current, sku: event.target.value }))} required><option value="">Select product</option>{products.map((item) => <option key={item.sku} value={item.sku}>{item.sku} — {item.name}</option>)}</select></label>
                  <label>Quantity<input type="number" min="1" step="1" value={transferForm.quantity} onChange={(event) => setTransferForm((current) => ({ ...current, quantity: event.target.value }))} required /></label>
                  {selectedTransferProduct?.isControlled && <label>Independent witness<select value={transferForm.witnessId} onChange={(event) => setTransferForm((current) => ({ ...current, witnessId: event.target.value }))} required><option value="">Select witness at dispatch</option>{branchStaff.filter((member) => member.id !== currentUser.id).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label>}
                  <button type="submit">Request transfer</button>
                </form> : <p className="form-error">Branch manager permission is required.</p>}
              </section>
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Branch transfers</h2><p>Dispatch from source and confirm receipt at destination.</p></div></div>
                {transfers.some((item) => (item.status === 'dispatched' && String(item.destinationBranchId) === String(activeBranchId) || item.status === 'requested' && String(item.sourceBranchId) === String(activeBranchId)) && item.lines.some((line) => line.isControlled)) && <label className="transfer-lot-input">Controlled stock movement witness
                  <select value={transferWitnessId} onChange={(event) => setTransferWitnessId(event.target.value)}><option value="">Select witness</option>{branchStaff.filter((member) => member.id !== currentUser.id).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select>
                </label>}
                <table><thead><tr><th>Reference</th><th>From</th><th>To</th><th>Items</th><th>Status</th><th>Action</th></tr></thead><tbody>
                  {transfers.map((item) => <tr key={item.id}><td>{item.reference}</td><td>{item.sourceBranch}</td><td>{item.destinationBranch}</td><td>{item.lines.map((line) => (
                    <div key={line.id} className="transfer-line">
                      <span>{line.sku} · {line.quantityReceived}/{line.quantityDispatched} received · lot {line.destinationBatch || line.batch}</span>
                      {canManageBranch && ['dispatched', 'partially_received'].includes(item.status) && String(item.destinationBranchId) === String(activeBranchId) && line.quantityOutstanding > 0 && <>
                        <label>Receive<input type="number" min="0" max={line.quantityOutstanding} step="1" value={transferReceiptQuantities[line.id] ?? line.quantityOutstanding} onChange={(event) => setTransferReceiptQuantities((current) => ({ ...current, [line.id]: event.target.value }))} /></label>
                        <label>Destination lot<input value={transferReceiptBatches[line.id] ?? line.destinationBatch ?? line.batch} onChange={(event) => setTransferReceiptBatches((current) => ({ ...current, [line.id]: event.target.value }))} /></label>
                      </>}
                    </div>
                  ))}</td><td>{item.status}</td>
                    <td>{canManageBranch && item.status === 'requested' && String(item.sourceBranchId) === String(activeBranchId) && <button type="button" onClick={() => handleTransferAction(item.id, 'dispatch')}>Dispatch</button>}{canManageBranch && ['dispatched', 'partially_received'].includes(item.status) && String(item.destinationBranchId) === String(activeBranchId) && <button type="button" onClick={() => handleTransferAction(item.id, 'receive')}>Receive selected quantities</button>}</td>
                  </tr>)}
                  {!transfers.length && <tr><td colSpan="6">No transfers involving this branch.</td></tr>}
                </tbody></table>
              </section>
            </>
          )}

          {activePage === 'Suppliers' && (
            <>
              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Supplier invoices</h2>
                    <p>Track invoice totals, due dates, payments, and balances.</p>
                  </div>
                  {canManageBranch && <button type="button" onClick={() => setShowSupplierInvoiceForm((shown) => !shown)}>
                    {showSupplierInvoiceForm ? 'Close invoice form' : 'Add supplier invoice'}
                  </button>
                  }
                  {canManageBranch && <button type="button" onClick={() => setShowSupplierPaymentForm((shown) => !shown)}>
                    {showSupplierPaymentForm ? 'Close payment form' : 'Record payment'}
                  </button>
                  }
                </div>

                {showSupplierInvoiceForm && canManageBranch && (
                  <form className="batch-form" onSubmit={handleSaveSupplierInvoice}>
                    <label>Supplier<select name="supplier" value={supplierInvoiceForm.supplier} onChange={handleSupplierInvoiceChange} required>
                      <option value="">Select supplier from directory</option>
                      {suppliers.map((item) => <option key={item.id} value={item.id}>{item.reference} — {item.name}</option>)}
                    </select></label>
                    <label>Supplier's invoice number<input name="invoiceNumber" value={supplierInvoiceForm.invoiceNumber} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Invoice total<input name="invoiceAmount" type="number" min="0.01" step="0.01" value={supplierInvoiceForm.invoiceAmount} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Amount already paid<input name="amountPaid" type="number" min="0" step="0.01" value={supplierInvoiceForm.amountPaid} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Due date<input name="dueDate" type="date" value={supplierInvoiceForm.dueDate} onChange={handleSupplierInvoiceChange} required /></label>
                    <label>Linked purchase order (optional)<select name="purchaseOrderId" value={supplierInvoiceForm.purchaseOrderId} onChange={handleSupplierInvoiceChange}><option value="">No linked order</option>{purchaseOrders.map((order) => <option key={order.id} value={order.id}>{order.number} — {order.supplier} ({order.status})</option>)}</select></label>
                    <label>Original supplier invoice (PDF, max 10 MB)<input ref={supplierInvoiceDocumentRef} name="originalDocument" type="file" accept="application/pdf,.pdf" onChange={handleSupplierInvoiceChange} /></label>
                    {supplierInvoiceError && <p className="form-error">{supplierInvoiceError}</p>}
                    <button type="submit">Save invoice</button>
                  </form>
                )}

                {showSupplierPaymentForm && canManageBranch && (
                  <form className="batch-form" onSubmit={handleRecordSupplierPayment}>
                    <label>Invoice<select name="invoiceId" value={supplierPaymentForm.invoiceId} onChange={handleSupplierPaymentChange} required>
                      <option value="">Select an unpaid invoice</option>
                      {supplierInvoices.filter((invoice) => invoice.invoiceAmount > invoice.amountPaid).map((invoice) => (
                        <option key={invoice.id} value={invoice.id}>{invoice.reference} — {invoice.supplier} — invoice {invoice.invoiceNumber} — balance {((invoice.invoiceAmount - invoice.amountPaid).toLocaleString())}</option>
                      ))}
                    </select></label>
                    <label>Payment amount<input name="amount" type="number" min="0.01" step="0.01" value={supplierPaymentForm.amount} onChange={handleSupplierPaymentChange} required /></label>
                    <label>Payment method<select name="method" value={supplierPaymentForm.method} onChange={handleSupplierPaymentChange} required>
                      <option value="">Select method</option><option value="Cash">Cash</option><option value="Mobile money">Mobile money</option><option value="Bank transfer">Bank transfer</option><option value="Card">Card</option>
                    </select></label>
                    <p className="generated-reference-note">A payment reference will be generated automatically.</p>
                    {supplierPaymentError && <p className="form-error">{supplierPaymentError}</p>}
                    <button type="submit">Save payment</button>
                  </form>
                )}

                <table>
                  <thead><tr><th>Supplier</th><th>System reference</th><th>Supplier invoice</th><th>Invoice total</th><th>Paid</th><th>Balance</th><th>Due date</th><th>Payment status</th><th>Reconciliation</th><th>Action</th><th>Documents</th></tr></thead>
                  <tbody>
                    {supplierInvoices.map((invoice) => {
                      const balance = invoice.invoiceAmount - invoice.amountPaid
                      const status = getSupplierInvoiceStatus(invoice)
                      const linkedOrder = purchaseOrders.find((order) => String(order.id) === String(invoice.purchaseOrderId))
                      return <tr key={invoice.id}>
                        <td>{invoice.supplier}</td><td>{invoice.reference}</td><td>{invoice.invoiceNumber}</td>
                        <td>{invoice.invoiceAmount.toLocaleString()}</td><td>{invoice.amountPaid.toLocaleString()}</td>
                        <td>{balance.toLocaleString()}</td><td>{invoice.dueDate}</td><td>{status}</td>
                        <td>{invoice.purchaseOrderId ? `${invoice.reconciliationStatus}${invoice.reconciledExpectedAmount !== null ? ` · expected ${invoice.reconciledExpectedAmount.toLocaleString()} · variance ${invoice.reconciliationVariance.toLocaleString()}` : ''}` : 'Not linked to an order'}</td>
                        <td>{canManageBranch && linkedOrder?.status === 'received' && <button type="button" onClick={() => handleReconcileSupplierInvoice(invoice.id)}>Reconcile</button>}</td>
                        <td>
                          <a href={`/api/supplier-invoices/${invoice.id}/reconciliation.pdf`} target="_blank" rel="noopener noreferrer">Reconciliation PDF</a>
                          {invoice.hasOriginalDocument && <> · <a href={`/api/supplier-invoices/${invoice.id}/original/`}>Original PDF</a></>}
                        </td>
                      </tr>
                    })}
                    {supplierInvoices.length === 0 && <tr><td colSpan="11">No supplier invoices recorded yet.</td></tr>}
                  </tbody>
                </table>
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Supplier payment history</h2><p>Payments entered against supplier invoices.</p></div></div>
                <table>
                  <thead><tr><th>Date</th><th>Supplier</th><th>System invoice</th><th>Supplier invoice</th><th>Amount</th><th>Method</th><th>Payment reference</th></tr></thead>
                  <tbody>
                    {supplierPayments.map((payment) => <tr key={payment.id}>
                      <td>{new Date(payment.recordedAt).toLocaleString()}</td><td>{payment.supplier}</td><td>{payment.invoiceReference}</td><td>{payment.invoiceNumber}</td><td>{payment.amount.toLocaleString()}</td><td>{payment.method}</td><td>{payment.reference}</td>
                    </tr>)}
                    {supplierPayments.length === 0 && <tr><td colSpan="7">No supplier payments recorded yet.</td></tr>}
                  </tbody>
                </table>
              </section>

              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Received stock by supplier</h2><p>Receipt records created when batches were added.</p></div></div>
                <table>
                  <thead><tr><th>Supplier</th><th>Medicine</th><th>Batch</th><th>Quantity received</th><th>Reference</th></tr></thead>
                  <tbody>
                    {stockMovements.filter((movement) => movement.type === 'Received').map((movement) => <tr key={movement.id}>
                      <td>{movement.supplier}</td><td>{movement.name}</td><td>{movement.batch}</td><td>{movement.quantity}</td><td>{movement.reference}</td>
                    </tr>)}
                    {!stockMovements.some((movement) => movement.type === 'Received') && <tr><td colSpan="5">No supplier receipts recorded yet.</td></tr>}
                  </tbody>
                </table>
              </section>
            </>
          )}

          {activePage === 'Administration' && currentUser.isStaff && (
            <>
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Product catalog</h2><p>Medicines and skincare share stock, purchasing, sales, and reporting. Expiry is required for medicines; record the skincare package date when provided, and keep period-after-opening separate. A unique SKU is assigned automatically.</p></div></div>
                <form className="batch-form" onSubmit={handleCreateProduct}>
                  <label>Name<input value={productForm.name} onChange={(event) => setProductForm((current) => ({ ...current, name: event.target.value }))} required /></label>
                  <label>Category<input value={productForm.category} onChange={(event) => setProductForm((current) => ({ ...current, category: event.target.value }))} required /></label>
                  <label>Product type
                    <select value={productForm.productType} onChange={(event) => setProductForm((current) => ({
                      ...current,
                      productType: event.target.value,
                      requiresPrescription: event.target.value === 'medicine' ? current.requiresPrescription : false,
                      isControlled: event.target.value === 'medicine' ? current.isControlled : false,
                      controlledSchedule: event.target.value === 'medicine' ? current.controlledSchedule : '',
                      ...(event.target.value === 'medicine' ? {
                        brand: '',
                        skinType: '',
                        skinConcerns: '',
                        keyIngredients: '',
                        usageInstructions: '',
                        warnings: '',
                        periodAfterOpeningMonths: '',
                      } : {}),
                    }))}>
                      <option value="medicine">Medicine</option>
                      <option value="skin_care">Skin care</option>
                    </select>
                  </label>
                  <label>Dispensing unit<input value={productForm.unit} onChange={(event) => setProductForm((current) => ({ ...current, unit: event.target.value }))} required /></label>
                  {productForm.productType === 'skin_care' ? <>
                    <label>Brand<input value={productForm.brand} onChange={(event) => setProductForm((current) => ({ ...current, brand: event.target.value }))} /></label>
                    <label>Skin type<input value={productForm.skinType} onChange={(event) => setProductForm((current) => ({ ...current, skinType: event.target.value }))} placeholder="For example: dry, oily, sensitive" /></label>
                    <label>Skin concerns<input value={productForm.skinConcerns} onChange={(event) => setProductForm((current) => ({ ...current, skinConcerns: event.target.value }))} placeholder="For example: dryness, sun protection" /></label>
                    <label>Key ingredients<textarea value={productForm.keyIngredients} onChange={(event) => setProductForm((current) => ({ ...current, keyIngredients: event.target.value }))} /></label>
                    <label>Label usage instructions<textarea value={productForm.usageInstructions} onChange={(event) => setProductForm((current) => ({ ...current, usageInstructions: event.target.value }))} /></label>
                    <label>Label warnings / allergens<textarea value={productForm.warnings} onChange={(event) => setProductForm((current) => ({ ...current, warnings: event.target.value }))} /></label>
                    <label>Period after opening (months)
                      <input type="number" min="1" step="1" value={productForm.periodAfterOpeningMonths} onChange={(event) => setProductForm((current) => ({ ...current, periodAfterOpeningMonths: event.target.value }))} />
                    </label>
                  </> : <>
                    <label className="checkbox-label"><input type="checkbox" checked={productForm.requiresPrescription} onChange={(event) => setProductForm((current) => ({ ...current, requiresPrescription: event.target.checked }))} /> Prescription required</label>
                    <label className="checkbox-label"><input type="checkbox" checked={productForm.isControlled} onChange={(event) => setProductForm((current) => ({ ...current, isControlled: event.target.checked }))} /> Controlled medicine</label>
                    <label>Controlled schedule (as configured)
                      <input value={productForm.controlledSchedule} onChange={(event) => setProductForm((current) => ({ ...current, controlledSchedule: event.target.value }))} />
                    </label>
                  </>}
                  <button type="submit">Add catalog product</button>
                </form>
                <table>
                  <thead><tr><th>SKU</th><th>Product</th><th>Type</th><th>Category</th><th>Brand</th><th>Skin-care label details</th></tr></thead>
                  <tbody>{products.map((product) => <tr key={product.sku}>
                    <td>{product.sku}</td>
                    <td>{product.name}</td>
                    <td>{product.productType === 'skin_care' ? 'Skin care' : 'Medicine'}</td>
                    <td>{product.category}</td>
                    <td>{product.brand || '—'}</td>
                    <td>{product.productType === 'skin_care' ? <>
                      {[product.skinType, product.skinConcerns].filter(Boolean).join(' · ') || '—'}
                      {product.periodAfterOpeningMonths && <p>PAO: {product.periodAfterOpeningMonths} months after opening</p>}
                      {(product.keyIngredients || product.usageInstructions || product.warnings) && <details>
                        <summary>Ingredients and label guidance</summary>
                        {product.keyIngredients && <p><strong>Ingredients:</strong> {product.keyIngredients}</p>}
                        {product.usageInstructions && <p><strong>Usage:</strong> {product.usageInstructions}</p>}
                        {product.warnings && <p><strong>Warnings:</strong> {product.warnings}</p>}
                      </details>}
                    </> : '—'}</td>
                  </tr>)}
                    {!products.length && <tr><td colSpan="6">No catalog products yet.</td></tr>}
                  </tbody>
                </table>
              </section>
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Supplier directory</h2><p>Maintain suppliers for purchase orders.</p></div></div>
                <form className="batch-form" onSubmit={handleCreateSupplier}>
                  <label>Supplier name<input value={supplierForm.name} onChange={(event) => setSupplierForm((current) => ({ ...current, name: event.target.value }))} required /></label>
                  <label>Contact name<input value={supplierForm.contactName} onChange={(event) => setSupplierForm((current) => ({ ...current, contactName: event.target.value }))} /></label>
                  <label>Email<input type="email" value={supplierForm.email} onChange={(event) => setSupplierForm((current) => ({ ...current, email: event.target.value }))} /></label>
                  <label>Phone<input value={supplierForm.phone} onChange={(event) => setSupplierForm((current) => ({ ...current, phone: event.target.value }))} /></label>
                  <label>Address<input value={supplierForm.address} onChange={(event) => setSupplierForm((current) => ({ ...current, address: event.target.value }))} /></label>
                  <button type="submit">Add supplier</button>
                </form>
                <table>
                  <thead><tr><th>Supplier code</th><th>Supplier</th><th>Phone</th><th>Email</th></tr></thead>
                  <tbody>
                    {suppliers.map((supplier) => (
                      <tr key={supplier.id}>
                        <td>{supplier.reference}</td>
                        <td>{supplier.name}</td>
                        <td>{supplier.phone || '—'}</td>
                        <td>{supplier.email || '—'}</td>
                      </tr>
                    ))}
                    {!suppliers.length && <tr><td colSpan="4">No suppliers recorded yet.</td></tr>}
                  </tbody>
                </table>
              </section>
              <section className="inventory-panel">
                <div className="inventory-heading"><div><h2>Supplier product terms</h2><p>Configure supplier SKU, unit cost, lead time, and the preferred supplier used for reorder drafts.</p></div></div>
                <form className="batch-form" onSubmit={handleSetSupplierProduct}>
                  <label>Product<select value={supplierProductForm.sku} onChange={(event) => setSupplierProductForm((current) => ({ ...current, sku: event.target.value }))} required><option value="">Select product</option>{products.map((item) => <option key={item.sku} value={item.sku}>{item.sku} — {item.name}</option>)}</select></label>
                  <label>Supplier<select value={supplierProductForm.supplierId} onChange={(event) => setSupplierProductForm((current) => ({ ...current, supplierId: event.target.value }))} required><option value="">Select supplier</option>{suppliers.map((item) => <option key={item.id} value={item.id}>{item.reference} — {item.name}</option>)}</select></label>
                  <label>Supplier SKU<input value={supplierProductForm.supplierSku} onChange={(event) => setSupplierProductForm((current) => ({ ...current, supplierSku: event.target.value }))} /></label>
                  <label>Unit cost<input type="number" min="0" step="0.01" value={supplierProductForm.unitCost} onChange={(event) => setSupplierProductForm((current) => ({ ...current, unitCost: event.target.value }))} required /></label>
                  <label>Lead time (days)<input type="number" min="0" step="1" value={supplierProductForm.leadTimeDays} onChange={(event) => setSupplierProductForm((current) => ({ ...current, leadTimeDays: event.target.value }))} required /></label>
                  <label className="checkbox-label"><input type="checkbox" checked={supplierProductForm.isPreferred} onChange={(event) => setSupplierProductForm((current) => ({ ...current, isPreferred: event.target.checked }))} /> Preferred supplier</label>
                  <button type="submit">Save supplier product terms</button>
                </form>
                {workflowError && <p className="form-error" role="alert">{workflowError}</p>}
              </section>
            </>
          )}

          {activePage === 'Reports' && (
            <>
              <section className="inventory-panel">
                <div className="inventory-heading">
                  <div><h2>Operational analytics</h2><p>Movement and sales totals for {branches.find((branch) => String(branch.id) === String(reportBranchId))?.name || 'the selected branch'} and the chosen date range. Values are operational summaries, not statutory reports.</p></div>
                  <button type="button" onClick={handleAnalyticsExport}>Export movement CSV</button>
                </div>
                <div className="report-filters">
                  <label>From<input type="date" value={reportStart} onChange={(event) => setReportStart(event.target.value)} /></label>
                  <label>To<input type="date" value={reportEnd} onChange={(event) => setReportEnd(event.target.value)} /></label>
                </div>
                {workflowError && <p className="form-error" role="alert">{workflowError}</p>}
                {analytics &&
                  String(analytics.branchId) === String(reportBranchId) &&
                  analytics.period.start === reportStart &&
                  analytics.period.end === reportEnd && <>
                  <div className="summary-cards report-summary-cards">
                    <article className="summary-card"><span>Received units</span><strong>{analytics.summary.unitsReceived}</strong></article>
                    <article className="summary-card"><span>Issued units</span><strong>{analytics.summary.unitsIssued}</strong></article>
                    <article className="summary-card">
                      <span>Approved sales</span>
                      <strong>{analytics.summary.salesAmount.toLocaleString()}</strong>
                      <small className={`report-change ${(analytics.summary.salesChangePercent ?? 0) >= 0 ? 'positive' : 'negative'}`}>
                        {analytics.summary.salesChangePercent === null
                          ? 'No sales in the comparison period'
                          : `${analytics.summary.salesChangePercent >= 0 ? '+' : ''}${analytics.summary.salesChangePercent.toFixed(1)}% vs previous period`}
                      </small>
                    </article>
                    <article className="summary-card"><span>Gross profit</span><strong>{analytics.summary.grossProfit.toLocaleString()}</strong></article>
                    <article className="summary-card"><span>Approved open balance</span><strong>{analytics.summary.outstandingBalance.toLocaleString()}</strong></article>
                    <article className="summary-card"><span>Pending approval</span><strong>{analytics.summary.pendingApprovalCount}</strong></article>
                  </div>
                  <div className="analytics-insights">
                    <section className="analytics-insight">
                      <h3>Daily sales trend</h3>
                      <div className="trend-list">
                        {analytics.salesTrend.slice(-14).map((day) => {
                          const peak = Math.max(...analytics.salesTrend.map((item) => item.salesAmount), 1)
                          return (
                            <div className="trend-row" key={day.date}>
                              <span>{new Date(`${day.date}T00:00:00`).toLocaleDateString()}</span>
                              <div className="trend-track" aria-hidden="true">
                                <div className="trend-bar" style={{ width: `${(day.salesAmount / peak) * 100}%` }} />
                              </div>
                              <strong>{day.salesAmount.toLocaleString()}</strong>
                            </div>
                          )
                        })}
                        {!analytics.salesTrend.some((day) => day.salesAmount > 0) && <p>No approved sales for this date range.</p>}
                      </div>
                    </section>
                    <section className="analytics-insight">
                      <h3>Top products by units sold</h3>
                      <table>
                        <thead><tr><th>Product</th><th>Units</th><th>Sales</th><th>Gross profit</th></tr></thead>
                        <tbody>
                          {analytics.topProducts.map((product) => (
                            <tr key={product.sku}>
                              <td>{product.product}</td>
                              <td>{product.unitsSold}</td>
                              <td>{product.salesAmount.toLocaleString()}</td>
                              <td>{product.grossProfit.toLocaleString()}</td>
                            </tr>
                          ))}
                          {!analytics.topProducts.length && <tr><td colSpan="4">No product sales for this date range.</td></tr>}
                        </tbody>
                      </table>
                    </section>
                    <section className="analytics-insight">
                      <h3>Stock risks to review</h3>
                      <p>{analytics.stockRisk.outOfStockLots} out-of-stock lots · {analytics.stockRisk.lowStockLots} low-stock lots · {analytics.stockRisk.expiringLots} lots expiring in 90 days</p>
                      <p>{analytics.stockRisk.reorderProducts} products currently meet reorder thresholds.</p>
                      {!isCrossBranchAnalytics && reorderSuggestions.length > 0 && (
                        <ul>
                          {reorderSuggestions.slice(0, 5).map((item) => (
                            <li key={item.sku}>{item.name}: {item.onHand} on hand, suggested order {item.suggestedQuantity}</li>
                          ))}
                        </ul>
                      )}
                    </section>
                  </div>
                  <div className="inventory-heading"><div><h2>Controlled medicine register</h2><p>Witness entries associated with recorded controlled stock movements.</p></div></div>
                  <table><thead><tr><th>Date</th><th>Product</th><th>Lot</th><th>Movement</th><th>Quantity</th><th>Witness</th><th>Balance after</th><th>Reference</th></tr></thead><tbody>
                    {analytics.controlledRegister.map((row, index) => <tr key={`${row.reference}-${index}`}><td>{new Date(row.date).toLocaleString()}</td><td>{row.product}</td><td>{row.batch}</td><td>{row.movement}</td><td>{row.quantity}</td><td>{row.witness}</td><td>{row.balanceAfter}</td><td>{row.reference}</td></tr>)}
                    {!analytics.controlledRegister.length && <tr><td colSpan="8">No controlled dispensing entries for this period.</td></tr>}
                  </tbody></table>
                </>}
              </section>

              {!isCrossBranchAnalytics && <section className="inventory-panel movement-panel">
              <div className="inventory-heading">
                <div>
                  <h2>Recent stock activity</h2>
                  <p>Track received, dispensed, and stock-count adjustments.</p>
                </div>
              </div>

              <table>
                <thead>
                  <tr>
                    <th>Date and time</th>
                    <th>Activity</th>
                    <th>Medicine</th>
                    <th>Batch</th>
                    <th>Quantity change</th>
                    <th>Supplier / recipient / reason</th>
                    <th>Reference</th>
                  </tr>
                </thead>

                <tbody>
                  {stockMovements.map((movement) => (
                    <tr key={movement.id}>
                      <td>{new Date(movement.recordedAt).toLocaleString()}</td>
                      <td>{movement.type}</td>
                      <td>{movement.name}</td>
                      <td>{movement.batch}</td>
                      <td>
                        {movement.quantity > 0 ? '+' : ''}
                        {movement.quantity}
                      </td>
                      <td>
                        {movement.recipient || movement.supplier || '—'}
                      </td>
                      <td>{movement.reference}</td>
                    </tr>
                  ))}

                  {stockMovements.length === 0 && (
                    <tr>
                      <td colSpan="7">No stock activity recorded yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </section>}

              {!isCrossBranchAnalytics && <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Sales and payments</h2>
                    <p>Recorded sales, amounts received, and outstanding balances.</p>
                  </div>
                  <button type="button" onClick={() => setShowCustomerPaymentForm((shown) => !shown)}>
                    {showCustomerPaymentForm ? 'Close payment form' : 'Record customer payment'}
                  </button>
                </div>

                {showCustomerPaymentForm && (
                  <form className="batch-form" onSubmit={handleRecordCustomerPayment}>
                    <label>Outstanding sale
                      <select name="saleId" value={customerPaymentForm.saleId} onChange={handleCustomerPaymentChange} required>
                        <option value="">Select a sale with a balance</option>
                        {sales.filter((sale) => sale.approvalStatus === 'approved' && sale.balanceDue > 0).map((sale) => (
                          <option key={sale.id} value={sale.id}>
                            {sale.recipient} — {sale.name} — {sale.reference} — due {sale.balanceDue.toLocaleString()}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>Payment amount
                      <input name="amount" type="number" min="0.01" step="0.01" value={customerPaymentForm.amount} onChange={handleCustomerPaymentChange} required />
                    </label>
                    <label>Payment method
                      <select name="method" value={customerPaymentForm.method} onChange={handleCustomerPaymentChange} required>
                        <option value="">Select method</option>
                        <option value="Cash">Cash</option>
                        <option value="Mobile money">Mobile money</option>
                        <option value="Bank transfer">Bank transfer</option>
                        <option value="Card">Card</option>
                      </select>
                    </label>
                    <p className="generated-reference-note">A payment reference will be generated automatically.</p>
                    {customerPaymentError && <p className="form-error">{customerPaymentError}</p>}
                    <button type="submit">Save customer payment</button>
                  </form>
                )}

                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Medicine</th>
                      <th>Quantity</th>
                      <th>Sale total</th>
                      {canViewFinancials && <th>Gross profit</th>}
                      <th>Received</th>
                      <th>Balance due</th>
                      <th>Approval</th>
                      <th>Submitted by</th>
                      <th>Approved by</th>
                      <th>Payment status</th>
                      <th>Original payment method</th>
                      <th>Reference</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sales.map((sale) => (
                      <tr key={sale.id}>
                        <td>{new Date(sale.recordedAt).toLocaleString()}</td>
                        <td>{sale.name}</td>
                        <td>{sale.quantity}</td>
                        <td>{sale.saleAmount.toLocaleString()}</td>
                        {canViewFinancials && <td>{sale.grossProfit.toLocaleString()}</td>}
                        <td>{sale.amountReceived.toLocaleString()}</td>
                        <td>{sale.balanceDue.toLocaleString()}</td>
                        <td>{sale.approvalStatus}</td>
                        <td>{sale.submittedBy}</td>
                        <td>{sale.approvedBy || '—'}</td>
                        <td>{getSalePaymentStatus(sale)}</td>
                        <td>{sale.paymentMethod || sale.proposedPaymentMethod}</td>
                        <td>{sale.reference}</td>
                        <td>
                          {canClinical && sale.approvalStatus === 'pending' && <>
                            <button type="button" onClick={() => handleApproveSale(sale.id)}>Approve</button>
                            <label>
                              Rejection reason
                              <input
                                value={saleRejectionReasons[sale.id] || ''}
                                onChange={(event) => setSaleRejectionReasons((current) => ({ ...current, [sale.id]: event.target.value }))}
                              />
                            </label>
                            <button type="button" onClick={() => handleRejectSale(sale.id)}>Reject</button>
                          </>}
                        </td>
                      </tr>
                    ))}
                    {sales.length === 0 && (
                      <tr>
                        <td colSpan={canViewFinancials ? 14 : 13}>No sales recorded yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </section>}
              {!isCrossBranchAnalytics && <section className="inventory-panel">
                <div className="inventory-heading">
                  <div>
                    <h2>Customer payment history</h2>
                    <p>Later payments recorded against sales.</p>
                  </div>
                </div>
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Customer</th>
                      <th>Sale reference</th>
                      <th>Amount</th>
                      <th>Method</th>
                      <th>Payment reference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {customerPayments.map((payment) => (
                      <tr key={payment.id}>
                        <td>{new Date(payment.recordedAt).toLocaleString()}</td>
                        <td>{payment.customer}</td>
                        <td>{payment.saleReference}</td>
                        <td>{payment.amount.toLocaleString()}</td>
                        <td>{payment.method}</td>
                        <td>{payment.reference}</td>
                      </tr>
                    ))}
                    {customerPayments.length === 0 && (
                      <tr><td colSpan="6">No later customer payments recorded yet.</td></tr>
                    )}
                  </tbody>
                </table>
              </section>}

            </>
          )}
        </section>
      </main>
    </div>
  )
}

export default App
