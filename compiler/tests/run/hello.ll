; sawc link manifest
; target arm64-apple-darwin
; speed -O0
; runtime hosted

target triple = "arm64-apple-macosx11.0.0"

@.bytes.0 = private unnamed_addr constant [12 x i8] c"hello, world"
@.bytes.1 = private unnamed_addr constant [9 x i8] c"hello.saw"
@"static std.panic.PANIC_REPORT" = internal global i64 0, align 8
@"static std.panic.PANIC_REPORTING" = internal global i64 0, align 8
@"static std.string.LENGTH_SLOT" = internal global i64 -1
@.bytes.2 = private unnamed_addr constant [9 x i8] c"panic.saw"
@.bytes.3 = private unnamed_addr constant { i64, i64, [6 x i8] } { i64 -1, i64 5, [6 x i8] c"write\00" }, align 16
@.bytes.4 = private unnamed_addr constant { i64, i64, [28 x i8] } { i64 -1, i64 27, [28 x i8] c"failed printing to stdout: \00" }, align 16
@"static std.stringbuilder.MIN_FIXED_CAPACITY" = internal global i64 5
@.bytes.5 = private unnamed_addr constant [17 x i8] c"stringbuilder.saw"
@.bytes.6 = private unnamed_addr constant [68 x i8] c"StringBuilder(bytes:capacity:): capacity is too small to format into"
@.bytes.7 = private unnamed_addr constant [15 x i8] c"systemerror.saw"
@.bytes.8 = private unnamed_addr constant { i64, i64, [10 x i8] } { i64 -1, i64 9, [10 x i8] c" failed (\00" }, align 16
@.bytes.9 = private unnamed_addr constant { i64, i64, [2 x i8] } { i64 -1, i64 1, [2 x i8] c")\00" }, align 16
@.bytes.10 = private unnamed_addr constant { i64, i64, [9 x i8] } { i64 -1, i64 8, [9 x i8] c", errno \00" }, align 16
@"static std.string.REFCOUNT_SLOT" = internal global i64 -2
@"static std.string.IMMORTAL" = internal global i64 -1
@"static std.systemerror.TAG_WOULD_BLOCK" = internal global i64 1
@"static std.systemerror.TAG_IN_PROGRESS" = internal global i64 2
@"static std.systemerror.TAG_ALREADY_CONNECTED" = internal global i64 3
@"static std.systemerror.TAG_INTERRUPTED" = internal global i64 4
@"static std.systemerror.TAG_CONNECTION_RESET" = internal global i64 5
@"static std.systemerror.TAG_CONNECTION_REFUSED" = internal global i64 6
@"static std.systemerror.TAG_CONNECTION_ABORTED" = internal global i64 7
@"static std.systemerror.TAG_BROKEN_PIPE" = internal global i64 8
@"static std.systemerror.TAG_NOT_CONNECTED" = internal global i64 9
@"static std.systemerror.TAG_NOT_FOUND" = internal global i64 10
@"static std.systemerror.TAG_PERMISSION_DENIED" = internal global i64 11
@"static std.systemerror.TAG_ALREADY_EXISTS" = internal global i64 12
@"static std.systemerror.TAG_ADDRESS_IN_USE" = internal global i64 13
@"static std.systemerror.TAG_INVALID_ARGUMENT" = internal global i64 14
@"static std.systemerror.TAG_RESOURCES_EXHAUSTED" = internal global i64 15
@"static std.systemerror.TAG_HOST_UNREACHABLE" = internal global i64 17
@"static std.systemerror.TAG_NETWORK_UNREACHABLE" = internal global i64 18
@"static std.systemerror.TAG_TIMED_OUT" = internal global i64 19
@"static std.systemerror.TAG_HOST_DOWN" = internal global i64 20
@"static std.systemerror.TAG_NETWORK_DOWN" = internal global i64 21
@"static std.systemerror.TAG_INVALID_DESCRIPTOR" = internal global i64 22
@"static std.systemerror.TAG_INPUT_OUTPUT_FAILED" = internal global i64 23
@.bytes.11 = private unnamed_addr constant { i64, i64, [12 x i8] } { i64 -1, i64 11, [12 x i8] c"would block\00" }, align 16
@.bytes.12 = private unnamed_addr constant { i64, i64, [12 x i8] } { i64 -1, i64 11, [12 x i8] c"in progress\00" }, align 16
@.bytes.13 = private unnamed_addr constant { i64, i64, [18 x i8] } { i64 -1, i64 17, [18 x i8] c"already connected\00" }, align 16
@.bytes.14 = private unnamed_addr constant { i64, i64, [12 x i8] } { i64 -1, i64 11, [12 x i8] c"interrupted\00" }, align 16
@.bytes.15 = private unnamed_addr constant { i64, i64, [17 x i8] } { i64 -1, i64 16, [17 x i8] c"connection reset\00" }, align 16
@.bytes.16 = private unnamed_addr constant { i64, i64, [19 x i8] } { i64 -1, i64 18, [19 x i8] c"connection refused\00" }, align 16
@.bytes.17 = private unnamed_addr constant { i64, i64, [19 x i8] } { i64 -1, i64 18, [19 x i8] c"connection aborted\00" }, align 16
@.bytes.18 = private unnamed_addr constant { i64, i64, [12 x i8] } { i64 -1, i64 11, [12 x i8] c"broken pipe\00" }, align 16
@.bytes.19 = private unnamed_addr constant { i64, i64, [14 x i8] } { i64 -1, i64 13, [14 x i8] c"not connected\00" }, align 16
@.bytes.20 = private unnamed_addr constant { i64, i64, [10 x i8] } { i64 -1, i64 9, [10 x i8] c"not found\00" }, align 16
@.bytes.21 = private unnamed_addr constant { i64, i64, [18 x i8] } { i64 -1, i64 17, [18 x i8] c"permission denied\00" }, align 16
@.bytes.22 = private unnamed_addr constant { i64, i64, [15 x i8] } { i64 -1, i64 14, [15 x i8] c"already exists\00" }, align 16
@.bytes.23 = private unnamed_addr constant { i64, i64, [15 x i8] } { i64 -1, i64 14, [15 x i8] c"address in use\00" }, align 16
@.bytes.24 = private unnamed_addr constant { i64, i64, [17 x i8] } { i64 -1, i64 16, [17 x i8] c"invalid argument\00" }, align 16
@.bytes.25 = private unnamed_addr constant { i64, i64, [20 x i8] } { i64 -1, i64 19, [20 x i8] c"resources exhausted\00" }, align 16
@.bytes.26 = private unnamed_addr constant { i64, i64, [12 x i8] } { i64 -1, i64 11, [12 x i8] c"other error\00" }, align 16
@.bytes.27 = private unnamed_addr constant { i64, i64, [17 x i8] } { i64 -1, i64 16, [17 x i8] c"host unreachable\00" }, align 16
@.bytes.28 = private unnamed_addr constant { i64, i64, [20 x i8] } { i64 -1, i64 19, [20 x i8] c"network unreachable\00" }, align 16
@.bytes.29 = private unnamed_addr constant { i64, i64, [10 x i8] } { i64 -1, i64 9, [10 x i8] c"timed out\00" }, align 16
@.bytes.30 = private unnamed_addr constant { i64, i64, [13 x i8] } { i64 -1, i64 12, [13 x i8] c"host is down\00" }, align 16
@.bytes.31 = private unnamed_addr constant { i64, i64, [16 x i8] } { i64 -1, i64 15, [16 x i8] c"network is down\00" }, align 16
@.bytes.32 = private unnamed_addr constant { i64, i64, [19 x i8] } { i64 -1, i64 18, [19 x i8] c"invalid descriptor\00" }, align 16
@.bytes.33 = private unnamed_addr constant { i64, i64, [20 x i8] } { i64 -1, i64 19, [20 x i8] c"input/output failed\00" }, align 16
@.bytes.34 = private unnamed_addr constant { i64, i64, [23 x i8] } { i64 -1, i64 22, [23 x i8] c"unexpected end of data\00" }, align 16
@.bytes.35 = private unnamed_addr constant { i64, i64, [34 x i8] } { i64 -1, i64 33, [34 x i8] c"the program could not be launched\00" }, align 16
@.bytes.36 = private unnamed_addr constant [10 x i8] c"string.saw"
@.bytes.37 = private unnamed_addr constant [63 x i8] c"String: over-release of a String reference (refcount underflow)"
@"static std.string.HEADER_WORDS" = internal global i64 2
@"static std.string.BLOCK_ALIGN" = internal global i64 16
@"static std.stringbuilder.MARKER_LEN" = internal global i64 3
@"static std.stringbuilder.FIRST_CAPACITY" = internal global i64 16
@.bytes.38 = private unnamed_addr constant [36 x i8] c"String.byte_at: index out of range: "
@.bytes.39 = private unnamed_addr constant [6 x i8] c" (len "
@.bytes.40 = private unnamed_addr constant [1 x i8] c")"
@.bytes.41 = private unnamed_addr constant [0 x i8] c""
@"static std.stringbuilder.MINUS_SIGN" = internal global i64 45
@"static std.stringbuilder.ASCII_ZERO" = internal global i64 48
@.bytes.42 = private unnamed_addr constant [7 x i8] c"mem.saw"
@"static std.stringbuilder.MARKER_BYTE_0" = internal global i64 226
@"static std.stringbuilder.MARKER_BYTE_1" = internal global i64 128
@"static std.stringbuilder.MARKER_BYTE_2" = internal global i64 166
@"static std.stringbuilder.CONTINUATION_FIRST" = internal global i64 128
@"static std.stringbuilder.CONTINUATION_END" = internal global i64 192
@__saw_bt_table = constant [33 x i8] c"SAWB\01\00@\00\00\00\00\00 \00\00\00 \00\00\00 \00\00\00\01\00\00\00\00\00\00\00\00", section "__TEXT,__sawbt", align 8
@llvm.used = appending global [1 x ptr] [ptr @__saw_bt_table], section "llvm.metadata"

declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)
declare i64 @__saw_rt_write_line(ptr, i64)
declare void @__saw_rt_panic(ptr, i64)
declare { i64, i1 } @llvm.ssub.with.overflow.i64(i64, i64)
declare i64 @__saw_rt_last_raw_code()
declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.smul.with.overflow.i64(i64, i64)
declare void @__saw_rt_dealloc(ptr, i64, i64)
declare ptr @__saw_rt_alloc(i64, i64)

define internal void @"saw hello.main()"() #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %t0 = alloca [16 x i8], align 8
  br label %bb0
bb0:
  store ptr @.bytes.0, ptr %t0
  %t1 = getelementptr i8, ptr %t0, i64 8
  store i64 12, ptr %t1
  %t2 = call i64 @__saw_rt_write_line(ptr %t0, i64 1)
  %t3 = icmp ne i64 %t2, 0
  br i1 %t3, label %print.failed.0, label %print.written.1
print.failed.0:
  call void @__saw_fail_print(ptr @.bytes.1, i64 9, i64 3, i64 %t2)
  unreachable
print.written.1:
  br label %bb1
bb1:
  ret void
}

define internal void @"saw std.panic.panic_sink(message: UnsafePointer<Int8>, length: Int)"(ptr %p1, i64 %p2) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca i64, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca ptr, align 8
  %l5 = alloca i64, align 8
  %l6 = alloca i8, align 1
  %l7 = alloca i8, align 1
  %l8 = alloca ptr, align 8
  %l9 = alloca i8, align 1
  %l10 = alloca [24 x i8], align 8
  %l11 = alloca ptr, align 8
  %l12 = alloca i64, align 8
  store ptr %p1, ptr %l1
  store i64 %p2, ptr %l2
  br label %bb0
bb0:
  store ptr @"static std.panic.PANIC_REPORT", ptr %l4
  %t0 = load ptr, ptr %l4
  %t1 = call i64 @"saw Atomic.load() args Int"(ptr %t0)
  store i64 %t1, ptr %l5
  br label %bb1
bb1:
  %t2 = load i64, ptr %l5
  store i64 %t2, ptr %l3
  %t3 = load i64, ptr %l3
  %t4 = icmp ne i64 %t3, 0
  %t5 = zext i1 %t4 to i8
  store i8 %t5, ptr %l7
  %t6 = load i8, ptr %l7
  %t7 = icmp ne i8 %t6, 0
  br i1 %t7, label %bb4, label %bb5
bb2:
  %t8 = load ptr, ptr %l1
  %t9 = load i64, ptr %l2
  call void @__saw_rt_panic(ptr %t8, i64 %t9)
  unreachable
bb3:
  %t10 = load i8, ptr %l6
  %t11 = icmp ne i8 %t10, 0
  br i1 %t11, label %bb7, label %bb8
bb4:
  store ptr @"static std.panic.PANIC_REPORTING", ptr %l8
  %t12 = load ptr, ptr %l8
  %t13 = call i8 @"saw Atomic.compare_exchange(expected: Int, desired: Int) args Int"(ptr %t12, i64 0, i64 1)
  store i8 %t13, ptr %l9
  br label %bb6
bb5:
  store i8 0, ptr %l6
  br label %bb3
bb6:
  %t14 = load i8, ptr %l9
  store i8 %t14, ptr %l6
  br label %bb3
bb7:
  %t15 = load i64, ptr %l3
  %t16 = inttoptr i64 %t15 to ptr
  store ptr %t16, ptr %l11
  store i64 0, ptr %l12
  %t17 = load ptr, ptr %l11
  %t18 = load i64, ptr %l12
  %t19 = mul i64 %t18, 24
  %t20 = getelementptr i8, ptr %t17, i64 %t19
  call void @"saw copy glue (UnsafePointer<Int8>, Int) unsafe sync -> Void"(ptr %l10, ptr %t20)
  %t21 = load ptr, ptr %l10
  %t22 = getelementptr i8, ptr %l10, i64 8
  %t23 = load ptr, ptr %t22
  %t24 = load ptr, ptr %l1
  %t25 = load i64, ptr %l2
  call void %t21(ptr %t23, ptr %t24, i64 %t25)
  br label %bb9
bb8:
  br label %bb2
bb9:
  %t26 = load ptr, ptr %l1
  call void @__saw_rt_panic(ptr %t26, i64 0)
  unreachable
}

define internal void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %ret, ptr %p1) #0 {
entry:
  %l0 = alloca [8 x i8], align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca [8 x i8], align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  store ptr %t0, ptr %l2
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l2, i64 8, i1 false)
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 8, i1 false)
  ret void
}

define internal ptr @"saw std.string.string_bytes(text: &String)"(ptr noalias %p1) #0 {
entry:
  %l0 = alloca ptr, align 8
  %l1 = alloca ptr, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = load ptr, ptr %t0
  store ptr %t1, ptr %l0
  %t2 = load ptr, ptr %l0
  ret ptr %t2
}

define internal i64 @"saw std.string.string_length(text: &String)"(ptr noalias %p1) #0 {
entry:
  %l0 = alloca i64, align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca i64, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  store ptr %t0, ptr %l2
  %t1 = load ptr, ptr %l2
  %t2 = call i64 @"saw std.string.String.len()"(ptr %t1)
  store i64 %t2, ptr %l3
  br label %bb1
bb1:
  %t3 = load i64, ptr %l3
  store i64 %t3, ptr %l0
  %t4 = load i64, ptr %l0
  ret i64 %t4
}

define internal i64 @"saw Atomic.load() args Int"(ptr %p1) #0 {
entry:
  %l0 = alloca i64, align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca i64, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  store ptr %t0, ptr %l2
  %t1 = load ptr, ptr %l2
  %t2 = call i64 @"saw atomic_load_word(a: &Atomic<T>) inst Int"(ptr %t1)
  store i64 %t2, ptr %l3
  br label %bb1
bb1:
  %t3 = load i64, ptr %l3
  store i64 %t3, ptr %l0
  %t4 = load i64, ptr %l0
  ret i64 %t4
}

define internal i8 @"saw Atomic.compare_exchange(expected: Int, desired: Int) args Int"(ptr %p1, i64 %p2, i64 %p3) #0 {
entry:
  %l0 = alloca i8, align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca i64, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca ptr, align 8
  %l5 = alloca i8, align 1
  store ptr %p1, ptr %l1
  store i64 %p2, ptr %l2
  store i64 %p3, ptr %l3
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  store ptr %t0, ptr %l4
  %t1 = load ptr, ptr %l4
  %t2 = load i64, ptr %l2
  %t3 = load i64, ptr %l3
  %t4 = call i8 @"saw atomic_exchange_word(a: &Atomic<T>, expected: Int, desired: Int) inst Int"(ptr %t1, i64 %t2, i64 %t3)
  store i8 %t4, ptr %l5
  br label %bb1
bb1:
  %t5 = load i8, ptr %l5
  store i8 %t5, ptr %l0
  %t6 = load i8, ptr %l0
  ret i8 %t6
}

define internal void @"saw copy glue (UnsafePointer<Int8>, Int) unsafe sync -> Void"(ptr %p1, ptr %p2) #0 {
entry:
  call void @llvm.memcpy.p0.p0.i64(ptr %p1, ptr %p2, i64 24, i1 false)
  %env.at = getelementptr i8, ptr %p1, i64 8
  %env = load ptr, ptr %env.at
  %release.at = getelementptr i8, ptr %p1, i64 16
  %release = load ptr, ptr %release.at
  %owns = icmp ne ptr %release, null
  br i1 %owns, label %owned, label %done
owned:
  %count.at = getelementptr i8, ptr %env, i64 -8
  %old = atomicrmw add ptr %count.at, i64 1 monotonic
  br label %done
done:
  ret void
}

define internal i64 @"saw std.string.String.len()"(ptr noalias %p1) #0 {
entry:
  %l0 = alloca i64, align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca ptr, align 8
  %l4 = alloca i64, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = load ptr, ptr %t0
  store ptr %t1, ptr %l3
  %t2 = load ptr, ptr %l3
  store ptr %t2, ptr %l2
  %t3 = load i64, ptr @"static std.string.LENGTH_SLOT"
  store i64 %t3, ptr %l4
  %t4 = load ptr, ptr %l2
  %t5 = load i64, ptr %l4
  %t6 = mul i64 %t5, 8
  %t7 = getelementptr i8, ptr %t4, i64 %t6
  %t8 = load i64, ptr %t7
  store i64 %t8, ptr %l0
  %t9 = load i64, ptr %l0
  ret i64 %t9
}

define internal i64 @"saw atomic_load_word(a: &Atomic<T>) inst Int"(ptr %p1) #0 {
entry:
  %l0 = alloca i64, align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca ptr, align 8
  %l4 = alloca ptr, align 8
  %l5 = alloca i64, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  store ptr %t0, ptr %l2
  %t1 = load ptr, ptr %l2
  %t2 = call ptr @"saw UnsafeMutableInterior.ptr() args Int"(ptr %t1)
  store ptr %t2, ptr %l3
  br label %bb1
bb1:
  %t3 = load ptr, ptr %l3
  store ptr %t3, ptr %l4
  %t4 = load ptr, ptr %l4
  %t5 = load atomic i64, ptr %t4 seq_cst, align 8
  store i64 %t5, ptr %l5
  br label %bb2
bb2:
  %t6 = load i64, ptr %l5
  store i64 %t6, ptr %l0
  %t7 = load i64, ptr %l0
  ret i64 %t7
}

define internal i8 @"saw atomic_exchange_word(a: &Atomic<T>, expected: Int, desired: Int) inst Int"(ptr %p1, i64 %p2, i64 %p3) #0 {
entry:
  %l0 = alloca i8, align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca i64, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca ptr, align 8
  %l5 = alloca ptr, align 8
  %l6 = alloca ptr, align 8
  %l7 = alloca i8, align 1
  store ptr %p1, ptr %l1
  store i64 %p2, ptr %l2
  store i64 %p3, ptr %l3
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  store ptr %t0, ptr %l4
  %t1 = load ptr, ptr %l4
  %t2 = call ptr @"saw UnsafeMutableInterior.ptr() args Int"(ptr %t1)
  store ptr %t2, ptr %l5
  br label %bb1
bb1:
  %t3 = load ptr, ptr %l5
  store ptr %t3, ptr %l6
  %t4 = load ptr, ptr %l6
  %t5 = load i64, ptr %l2
  %t6 = load i64, ptr %l3
  %t7 = cmpxchg ptr %t4, i64 %t5, i64 %t6 seq_cst seq_cst
  %t8 = extractvalue { i64, i1 } %t7, 1
  %t9 = zext i1 %t8 to i8
  store i8 %t9, ptr %l7
  br label %bb2
bb2:
  %t10 = load i8, ptr %l7
  store i8 %t10, ptr %l0
  %t11 = load i8, ptr %l0
  ret i8 %t11
}

define internal ptr @"saw UnsafeMutableInterior.ptr() args Int"(ptr %p1) #0 {
entry:
  %l0 = alloca ptr, align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca ptr, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  store ptr %t0, ptr %l2
  %t1 = load ptr, ptr %l2
  store ptr %t1, ptr %l3
  %t2 = load ptr, ptr %l3
  store ptr %t2, ptr %l0
  %t3 = load ptr, ptr %l0
  ret ptr %t3
}

define internal i64 @"saw std.panic.print_failure(status: Int, bytes: UnsafePointer<Int8>, capacity: Int)"(i64 %p1, ptr %p2, i64 %p3) #0 {
entry:
  %l0 = alloca i64, align 8
  %l1 = alloca i64, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca [24 x i8], align 8
  %l5 = alloca i64, align 8
  %l6 = alloca [24 x i8], align 8
  %l7 = alloca [40 x i8], align 8
  %l8 = alloca [40 x i8], align 8
  %l9 = alloca ptr, align 8
  %l10 = alloca [24 x i8], align 8
  %l11 = alloca [0 x i8], align 1
  %l12 = alloca ptr, align 8
  %l13 = alloca ptr, align 8
  %l14 = alloca ptr, align 8
  %l15 = alloca i64, align 8
  %t4 = alloca [8 x i8], align 8
  %t10 = alloca [8 x i8], align 8
  store i64 %p1, ptr %l1
  store ptr %p2, ptr %l2
  store i64 %p3, ptr %l3
  br label %bb0
bb0:
  %t0 = load i64, ptr %l1
  %t1 = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 0, i64 %t0)
  %t2 = extractvalue { i64, i1 } %t1, 0
  %t3 = extractvalue { i64, i1 } %t1, 1
  br i1 %t3, label %check.0, label %checked.1
check.0:
  call void @__saw_fail_overflow(ptr @.bytes.2, i64 9, i64 47)
  unreachable
checked.1:
  store i64 %t2, ptr %l5
  %t5 = getelementptr i8, ptr @.bytes.3, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %t4, ptr %t5)
  %t6 = load i64, ptr %l5
  call void @"saw std.systemerror.SystemError.of(operation: String, tag: Int)"(ptr %l6, ptr %t4, i64 %t6)
  br label %bb1
bb1:
  call void @llvm.memcpy.p0.p0.i64(ptr %l4, ptr %l6, i64 24, i1 false)
  %t7 = load ptr, ptr %l2
  %t8 = load i64, ptr %l3
  call void @"saw std.stringbuilder.StringBuilder.init(bytes: UnsafePointer<Int8>, capacity: Int)"(ptr %l8, ptr %t7, i64 %t8)
  br label %bb2
bb2:
  call void @llvm.memcpy.p0.p0.i64(ptr %l7, ptr %l8, i64 40, i1 false)
  store ptr %l7, ptr %l9
  %t9 = load ptr, ptr %l9
  %t11 = getelementptr i8, ptr @.bytes.4, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %t10, ptr %t11)
  call void @"saw std.stringbuilder.StringBuilder.append(s: String)"(ptr %l10, ptr %t9, ptr %t10)
  br label %bb3
bb3:
  %t12 = load i32, ptr %l10
  %t13 = zext i32 %t12 to i64
  %t14 = icmp eq i64 %t13, 0
  br i1 %t14, label %forced.2, label %unforced.3
unforced.3:
  call void @__saw_fail_try(ptr @.bytes.2, i64 9, i64 49)
  unreachable
forced.2:
  %t15 = getelementptr i8, ptr %l10, i64 8
  call void @"saw drop glue Result<Void, std.alloc.AllocError>"(ptr %l10)
  store ptr %l7, ptr %l12
  store ptr %l4, ptr %l13
  %t16 = load ptr, ptr %l13
  %t17 = load ptr, ptr %l12
  call void @"saw std.systemerror.SystemError.format(into: &var std.stringbuilder.StringBuilder)"(ptr %t16, ptr %t17)
  br label %bb4
bb4:
  store ptr %l7, ptr %l14
  %t18 = load ptr, ptr %l14
  %t19 = call i64 @"saw std.stringbuilder.StringBuilder.len()"(ptr %t18)
  store i64 %t19, ptr %l15
  br label %bb5
bb5:
  %t20 = load i64, ptr %l15
  store i64 %t20, ptr %l0
  call void @"saw drop glue std.stringbuilder.StringBuilder"(ptr %l7)
  call void @"saw drop glue std.systemerror.SystemError"(ptr %l4)
  %t21 = load i64, ptr %l0
  ret i64 %t21
}

define internal void @"saw std.systemerror.SystemError.of(operation: String, tag: Int)"(ptr %ret, ptr %p1, i64 %p2) #0 {
entry:
  %l0 = alloca [24 x i8], align 8
  %l1 = alloca [8 x i8], align 8
  %l2 = alloca i64, align 8
  %l3 = alloca ptr, align 8
  %l4 = alloca [8 x i8], align 8
  %l5 = alloca [4 x i8], align 4
  %l6 = alloca i64, align 8
  %l7 = alloca [24 x i8], align 8
  call void @llvm.memcpy.p0.p0.i64(ptr %l1, ptr %p1, i64 8, i1 false)
  store i64 %p2, ptr %l2
  br label %bb0
bb0:
  store ptr %l1, ptr %l3
  %t0 = load ptr, ptr %l3
  call void @"saw std.string.String.copy()"(ptr %l4, ptr %t0)
  br label %bb1
bb1:
  %t1 = load i64, ptr %l2
  call void @"saw std.systemerror.system_error_kind(tag: Int)"(ptr %l5, i64 %t1)
  br label %bb2
bb2:
  %t2 = call i64 @__saw_rt_last_raw_code()
  store i64 %t2, ptr %l6
  br label %bb3
bb3:
  call void @llvm.memcpy.p0.p0.i64(ptr %l7, ptr %l4, i64 8, i1 false)
  %t3 = getelementptr i8, ptr %l7, i64 8
  call void @llvm.memcpy.p0.p0.i64(ptr %t3, ptr %l5, i64 4, i1 false)
  %t4 = getelementptr i8, ptr %l7, i64 16
  %t5 = load i64, ptr %l6
  store i64 %t5, ptr %t4
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l7, i64 24, i1 false)
  call void @"saw drop glue String"(ptr %l1)
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 24, i1 false)
  ret void
}

define internal void @"saw std.stringbuilder.StringBuilder.init(bytes: UnsafePointer<Int8>, capacity: Int)"(ptr %ret, ptr %p1, i64 %p2) #0 {
entry:
  %l0 = alloca [40 x i8], align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca i64, align 8
  %l3 = alloca i8, align 1
  %l4 = alloca i64, align 8
  %l5 = alloca [16 x i8], align 8
  %l6 = alloca [40 x i8], align 8
  store ptr %p1, ptr %l1
  store i64 %p2, ptr %l2
  br label %bb0
bb0:
  %t0 = load i64, ptr %l2
  %t1 = load i64, ptr @"static std.stringbuilder.MIN_FIXED_CAPACITY"
  %t2 = icmp slt i64 %t0, %t1
  %t3 = zext i1 %t2 to i8
  store i8 %t3, ptr %l3
  %t4 = load i8, ptr %l3
  %t5 = icmp ne i8 %t4, 0
  br i1 %t5, label %bb2, label %bb3
bb1:
  store i64 0, ptr %l4
  %t6 = load ptr, ptr %l1
  %t7 = load i64, ptr %l4
  %t8 = mul i64 %t7, 1
  %t9 = getelementptr i8, ptr %t6, i64 %t8
  store i8 0, ptr %t9
  store i8 1, ptr %l5
  %t10 = getelementptr i8, ptr %l5, i64 8
  %t11 = load ptr, ptr %l1
  store ptr %t11, ptr %t10
  call void @llvm.memcpy.p0.p0.i64(ptr %l6, ptr %l5, i64 16, i1 false)
  %t12 = getelementptr i8, ptr %l6, i64 16
  store i64 0, ptr %t12
  %t13 = getelementptr i8, ptr %l6, i64 24
  %t14 = load i64, ptr %l2
  store i64 %t14, ptr %t13
  %t15 = getelementptr i8, ptr %l6, i64 32
  store i8 1, ptr %t15
  %t16 = getelementptr i8, ptr %l6, i64 33
  store i8 0, ptr %t16
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l6, i64 40, i1 false)
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 40, i1 false)
  ret void
bb2:
  call void @__saw_fail(ptr @.bytes.5, i64 17, i64 75, ptr @.bytes.6, i64 68)
  unreachable
  unreachable
bb3:
  br label %bb1
}

define internal void @"saw std.stringbuilder.StringBuilder.append(s: String)"(ptr %ret, ptr noalias %p1, ptr %p2) #0 {
entry:
  %l0 = alloca [24 x i8], align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca [8 x i8], align 8
  %l3 = alloca ptr, align 8
  %l4 = alloca ptr, align 8
  %l5 = alloca [24 x i8], align 8
  store ptr %p1, ptr %l1
  call void @llvm.memcpy.p0.p0.i64(ptr %l2, ptr %p2, i64 8, i1 false)
  br label %bb0
bb0:
  store ptr %l2, ptr %l3
  %t0 = load ptr, ptr %l1
  store ptr %t0, ptr %l4
  %t1 = load ptr, ptr %l4
  %t2 = load ptr, ptr %l3
  call void @"saw std.stringbuilder.StringBuilder.append_text(s: &String)"(ptr %l5, ptr %t1, ptr %t2)
  br label %bb1
bb1:
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l5, i64 24, i1 false)
  call void @"saw drop glue String"(ptr %l2)
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 24, i1 false)
  ret void
}

define internal void @"saw drop glue Result<Void, std.alloc.AllocError>"(ptr noalias %p1) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = load i32, ptr %t0
  %t2 = zext i32 %t1 to i64
  switch i64 %t2, label %nocase.0 [ i64 0, label %bb2 i64 1, label %bb3 ]
nocase.0:
  unreachable
bb1:
  ret void
bb2:
  br label %bb1
bb3:
  br label %bb1
}

define internal void @"saw std.systemerror.SystemError.format(into: &var std.stringbuilder.StringBuilder)"(ptr noalias %p1, ptr noalias %p2) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca ptr, align 8
  %l4 = alloca [8 x i8], align 8
  %l5 = alloca ptr, align 8
  %l6 = alloca [24 x i8], align 8
  %l7 = alloca [0 x i8], align 1
  %l8 = alloca ptr, align 8
  %l9 = alloca [24 x i8], align 8
  %l10 = alloca [0 x i8], align 1
  %l11 = alloca ptr, align 8
  %l12 = alloca [8 x i8], align 8
  %l13 = alloca ptr, align 8
  %l14 = alloca [24 x i8], align 8
  %l15 = alloca [0 x i8], align 1
  %l16 = alloca i8, align 1
  %l17 = alloca i8, align 1
  %l18 = alloca i8, align 1
  %l19 = alloca ptr, align 8
  %l20 = alloca [24 x i8], align 8
  %l21 = alloca [0 x i8], align 1
  %l22 = alloca i64, align 8
  %l23 = alloca ptr, align 8
  %l24 = alloca [24 x i8], align 8
  %l25 = alloca [0 x i8], align 1
  %l26 = alloca ptr, align 8
  %l27 = alloca [24 x i8], align 8
  %l28 = alloca [0 x i8], align 1
  %t10 = alloca [8 x i8], align 8
  %t33 = alloca [8 x i8], align 8
  %t45 = alloca [8 x i8], align 8
  store ptr %p1, ptr %l1
  store ptr %p2, ptr %l2
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  store ptr %t0, ptr %l3
  %t1 = load ptr, ptr %l3
  call void @"saw std.string.String.copy()"(ptr %l4, ptr %t1)
  br label %bb1
bb1:
  %t2 = load ptr, ptr %l2
  store ptr %t2, ptr %l5
  %t3 = load ptr, ptr %l5
  call void @"saw std.stringbuilder.StringBuilder.append(s: String)"(ptr %l6, ptr %t3, ptr %l4)
  br label %bb2
bb2:
  %t4 = load i32, ptr %l6
  %t5 = zext i32 %t4 to i64
  %t6 = icmp eq i64 %t5, 0
  br i1 %t6, label %forced.0, label %unforced.1
unforced.1:
  call void @__saw_fail_try(ptr @.bytes.7, i64 15, i64 252)
  unreachable
forced.0:
  %t7 = getelementptr i8, ptr %l6, i64 8
  call void @"saw drop glue Result<Void, std.alloc.AllocError>"(ptr %l6)
  %t8 = load ptr, ptr %l2
  store ptr %t8, ptr %l8
  %t9 = load ptr, ptr %l8
  %t11 = getelementptr i8, ptr @.bytes.8, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %t10, ptr %t11)
  call void @"saw std.stringbuilder.StringBuilder.append(s: String)"(ptr %l9, ptr %t9, ptr %t10)
  br label %bb3
bb3:
  %t12 = load i32, ptr %l9
  %t13 = zext i32 %t12 to i64
  %t14 = icmp eq i64 %t13, 0
  br i1 %t14, label %forced.2, label %unforced.3
unforced.3:
  call void @__saw_fail_try(ptr @.bytes.7, i64 15, i64 253)
  unreachable
forced.2:
  %t15 = getelementptr i8, ptr %l9, i64 8
  call void @"saw drop glue Result<Void, std.alloc.AllocError>"(ptr %l9)
  %t16 = load ptr, ptr %l1
  %t17 = getelementptr i8, ptr %t16, i64 8
  store ptr %t17, ptr %l11
  %t18 = load ptr, ptr %l11
  call void @"saw std.systemerror.SystemErrorKind.describe()"(ptr %l12, ptr %t18)
  br label %bb4
bb4:
  %t19 = load ptr, ptr %l2
  store ptr %t19, ptr %l13
  %t20 = load ptr, ptr %l13
  call void @"saw std.stringbuilder.StringBuilder.append(s: String)"(ptr %l14, ptr %t20, ptr %l12)
  br label %bb5
bb5:
  %t21 = load i32, ptr %l14
  %t22 = zext i32 %t21 to i64
  %t23 = icmp eq i64 %t22, 0
  br i1 %t23, label %forced.4, label %unforced.5
unforced.5:
  call void @__saw_fail_try(ptr @.bytes.7, i64 15, i64 254)
  unreachable
forced.4:
  %t24 = getelementptr i8, ptr %l14, i64 8
  call void @"saw drop glue Result<Void, std.alloc.AllocError>"(ptr %l14)
  %t25 = load ptr, ptr %l1
  %t26 = getelementptr i8, ptr %t25, i64 8
  %t27 = load i32, ptr %t26
  %t28 = zext i32 %t27 to i64
  switch i64 %t28, label %bb8 [ i64 15, label %bb7 ]
bb6:
  %t29 = load i8, ptr %l16
  %t30 = icmp ne i8 %t29, 0
  br i1 %t30, label %bb13, label %bb14
bb7:
  br label %bb9
bb8:
  br label %bb10
bb9:
  store i8 1, ptr %l16
  br label %bb6
bb10:
  store i8 0, ptr %l16
  br label %bb6
bb11:
  %t31 = load ptr, ptr %l2
  store ptr %t31, ptr %l26
  %t32 = load ptr, ptr %l26
  %t34 = getelementptr i8, ptr @.bytes.9, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %t33, ptr %t34)
  call void @"saw std.stringbuilder.StringBuilder.append(s: String)"(ptr %l27, ptr %t32, ptr %t33)
  br label %bb19
bb12:
  %t35 = load i8, ptr %l17
  %t36 = icmp ne i8 %t35, 0
  br i1 %t36, label %bb15, label %bb16
bb13:
  %t37 = load ptr, ptr %l1
  %t38 = getelementptr i8, ptr %t37, i64 16
  %t39 = load i64, ptr %t38
  %t40 = icmp ne i64 %t39, 0
  %t41 = zext i1 %t40 to i8
  store i8 %t41, ptr %l18
  %t42 = load i8, ptr %l18
  store i8 %t42, ptr %l17
  br label %bb12
bb14:
  store i8 0, ptr %l17
  br label %bb12
bb15:
  %t43 = load ptr, ptr %l2
  store ptr %t43, ptr %l19
  %t44 = load ptr, ptr %l19
  %t46 = getelementptr i8, ptr @.bytes.10, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %t45, ptr %t46)
  call void @"saw std.stringbuilder.StringBuilder.append(s: String)"(ptr %l20, ptr %t44, ptr %t45)
  br label %bb17
bb16:
  br label %bb11
bb17:
  %t47 = load i32, ptr %l20
  %t48 = zext i32 %t47 to i64
  %t49 = icmp eq i64 %t48, 0
  br i1 %t49, label %forced.6, label %unforced.7
unforced.7:
  call void @__saw_fail_try(ptr @.bytes.7, i64 15, i64 260)
  unreachable
forced.6:
  %t50 = getelementptr i8, ptr %l20, i64 8
  call void @"saw drop glue Result<Void, std.alloc.AllocError>"(ptr %l20)
  %t51 = load ptr, ptr %l1
  %t52 = getelementptr i8, ptr %t51, i64 16
  %t53 = load i64, ptr %t52
  store i64 %t53, ptr %l22
  %t54 = load ptr, ptr %l2
  store ptr %t54, ptr %l23
  %t55 = load ptr, ptr %l23
  %t56 = load i64, ptr %l22
  call void @"saw std.stringbuilder.StringBuilder.append(value: Int)"(ptr %l24, ptr %t55, i64 %t56)
  br label %bb18
bb18:
  %t57 = load i32, ptr %l24
  %t58 = zext i32 %t57 to i64
  %t59 = icmp eq i64 %t58, 0
  br i1 %t59, label %forced.8, label %unforced.9
unforced.9:
  call void @__saw_fail_try(ptr @.bytes.7, i64 15, i64 261)
  unreachable
forced.8:
  %t60 = getelementptr i8, ptr %l24, i64 8
  call void @"saw drop glue Result<Void, std.alloc.AllocError>"(ptr %l24)
  br label %bb11
bb19:
  %t61 = load i32, ptr %l27
  %t62 = zext i32 %t61 to i64
  %t63 = icmp eq i64 %t62, 0
  br i1 %t63, label %forced.10, label %unforced.11
unforced.11:
  call void @__saw_fail_try(ptr @.bytes.7, i64 15, i64 263)
  unreachable
forced.10:
  %t64 = getelementptr i8, ptr %l27, i64 8
  call void @"saw drop glue Result<Void, std.alloc.AllocError>"(ptr %l27)
  ret void
}

define internal i64 @"saw std.stringbuilder.StringBuilder.len()"(ptr noalias %p1) #0 {
entry:
  %l0 = alloca i64, align 8
  %l1 = alloca ptr, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = getelementptr i8, ptr %t0, i64 16
  %t2 = load i64, ptr %t1
  store i64 %t2, ptr %l0
  %t3 = load i64, ptr %l0
  ret i64 %t3
}

define internal void @"saw drop glue std.stringbuilder.StringBuilder"(ptr noalias %p1) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  store ptr %t0, ptr %l2
  %t1 = load ptr, ptr %l2
  call void @"saw std.stringbuilder.StringBuilder.deinit()"(ptr %t1)
  br label %bb1
bb1:
  ret void
}

define internal void @"saw drop glue std.systemerror.SystemError"(ptr noalias %p1) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  call void @"saw drop glue String"(ptr %t0)
  ret void
}

define internal void @"saw std.string.String.copy()"(ptr %ret, ptr noalias %p1) #0 {
entry:
  %l0 = alloca [8 x i8], align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca ptr, align 8
  %l4 = alloca ptr, align 8
  %l5 = alloca i64, align 8
  %l6 = alloca ptr, align 8
  %l7 = alloca ptr, align 8
  %l8 = alloca i64, align 8
  %l9 = alloca i8, align 1
  %l10 = alloca i64, align 8
  %l11 = alloca [8 x i8], align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = load ptr, ptr %t0
  store ptr %t1, ptr %l3
  %t2 = load ptr, ptr %l3
  store ptr %t2, ptr %l2
  %t3 = load i64, ptr @"static std.string.REFCOUNT_SLOT"
  store i64 %t3, ptr %l5
  %t4 = load ptr, ptr %l2
  %t5 = load i64, ptr %l5
  %t6 = mul i64 %t5, 8
  %t7 = getelementptr i8, ptr %t4, i64 %t6
  store ptr %t7, ptr %l6
  %t8 = load ptr, ptr %l6
  store ptr %t8, ptr %l7
  %t9 = load ptr, ptr %l7
  store ptr %t9, ptr %l4
  %t10 = load ptr, ptr %l4
  %t11 = load atomic i64, ptr %t10 monotonic, align 8
  store i64 %t11, ptr %l8
  br label %bb2
bb1:
  %t12 = load ptr, ptr %l1
  %t13 = load ptr, ptr %t12
  store ptr %t13, ptr %l11
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l11, i64 8, i1 false)
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 8, i1 false)
  ret void
bb2:
  %t14 = load i64, ptr %l8
  %t15 = load i64, ptr @"static std.string.IMMORTAL"
  %t16 = icmp ne i64 %t14, %t15
  %t17 = zext i1 %t16 to i8
  store i8 %t17, ptr %l9
  %t18 = load i8, ptr %l9
  %t19 = icmp ne i8 %t18, 0
  br i1 %t19, label %bb3, label %bb4
bb3:
  %t20 = load ptr, ptr %l4
  %t21 = atomicrmw add ptr %t20, i64 1 monotonic
  store i64 %t21, ptr %l10
  br label %bb5
bb4:
  br label %bb1
bb5:
  br label %bb1
}

define internal void @"saw std.systemerror.system_error_kind(tag: Int)"(ptr %ret, i64 %p1) #0 {
entry:
  %l0 = alloca [4 x i8], align 4
  %l1 = alloca i64, align 8
  %l2 = alloca i8, align 1
  %l3 = alloca [4 x i8], align 4
  %l4 = alloca i8, align 1
  %l5 = alloca [4 x i8], align 4
  %l6 = alloca i8, align 1
  %l7 = alloca [4 x i8], align 4
  %l8 = alloca i8, align 1
  %l9 = alloca [4 x i8], align 4
  %l10 = alloca i8, align 1
  %l11 = alloca [4 x i8], align 4
  %l12 = alloca i8, align 1
  %l13 = alloca [4 x i8], align 4
  %l14 = alloca i8, align 1
  %l15 = alloca [4 x i8], align 4
  %l16 = alloca i8, align 1
  %l17 = alloca [4 x i8], align 4
  %l18 = alloca i8, align 1
  %l19 = alloca [4 x i8], align 4
  %l20 = alloca i8, align 1
  %l21 = alloca [4 x i8], align 4
  %l22 = alloca i8, align 1
  %l23 = alloca [4 x i8], align 4
  %l24 = alloca i8, align 1
  %l25 = alloca [4 x i8], align 4
  %l26 = alloca i8, align 1
  %l27 = alloca [4 x i8], align 4
  %l28 = alloca i8, align 1
  %l29 = alloca [4 x i8], align 4
  %l30 = alloca i8, align 1
  %l31 = alloca [4 x i8], align 4
  %l32 = alloca i8, align 1
  %l33 = alloca [4 x i8], align 4
  %l34 = alloca i8, align 1
  %l35 = alloca [4 x i8], align 4
  %l36 = alloca i8, align 1
  %l37 = alloca [4 x i8], align 4
  %l38 = alloca i8, align 1
  %l39 = alloca [4 x i8], align 4
  %l40 = alloca i8, align 1
  %l41 = alloca [4 x i8], align 4
  %l42 = alloca i8, align 1
  %l43 = alloca [4 x i8], align 4
  %l44 = alloca i8, align 1
  %l45 = alloca [4 x i8], align 4
  %l46 = alloca [4 x i8], align 4
  store i64 %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load i64, ptr %l1
  %t1 = load i64, ptr @"static std.systemerror.TAG_WOULD_BLOCK"
  %t2 = icmp eq i64 %t0, %t1
  %t3 = zext i1 %t2 to i8
  store i8 %t3, ptr %l2
  %t4 = load i8, ptr %l2
  %t5 = icmp ne i8 %t4, 0
  br i1 %t5, label %bb2, label %bb3
bb1:
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 4, i1 false)
  ret void
bb2:
  store i32 0, ptr %l3
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l3, i64 4, i1 false)
  br label %bb1
bb3:
  %t6 = load i64, ptr %l1
  %t7 = load i64, ptr @"static std.systemerror.TAG_IN_PROGRESS"
  %t8 = icmp eq i64 %t6, %t7
  %t9 = zext i1 %t8 to i8
  store i8 %t9, ptr %l4
  %t10 = load i8, ptr %l4
  %t11 = icmp ne i8 %t10, 0
  br i1 %t11, label %bb4, label %bb5
bb4:
  store i32 1, ptr %l5
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l5, i64 4, i1 false)
  br label %bb1
bb5:
  %t12 = load i64, ptr %l1
  %t13 = load i64, ptr @"static std.systemerror.TAG_ALREADY_CONNECTED"
  %t14 = icmp eq i64 %t12, %t13
  %t15 = zext i1 %t14 to i8
  store i8 %t15, ptr %l6
  %t16 = load i8, ptr %l6
  %t17 = icmp ne i8 %t16, 0
  br i1 %t17, label %bb6, label %bb7
bb6:
  store i32 2, ptr %l7
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l7, i64 4, i1 false)
  br label %bb1
bb7:
  %t18 = load i64, ptr %l1
  %t19 = load i64, ptr @"static std.systemerror.TAG_INTERRUPTED"
  %t20 = icmp eq i64 %t18, %t19
  %t21 = zext i1 %t20 to i8
  store i8 %t21, ptr %l8
  %t22 = load i8, ptr %l8
  %t23 = icmp ne i8 %t22, 0
  br i1 %t23, label %bb8, label %bb9
bb8:
  store i32 3, ptr %l9
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l9, i64 4, i1 false)
  br label %bb1
bb9:
  %t24 = load i64, ptr %l1
  %t25 = load i64, ptr @"static std.systemerror.TAG_CONNECTION_RESET"
  %t26 = icmp eq i64 %t24, %t25
  %t27 = zext i1 %t26 to i8
  store i8 %t27, ptr %l10
  %t28 = load i8, ptr %l10
  %t29 = icmp ne i8 %t28, 0
  br i1 %t29, label %bb10, label %bb11
bb10:
  store i32 4, ptr %l11
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l11, i64 4, i1 false)
  br label %bb1
bb11:
  %t30 = load i64, ptr %l1
  %t31 = load i64, ptr @"static std.systemerror.TAG_CONNECTION_REFUSED"
  %t32 = icmp eq i64 %t30, %t31
  %t33 = zext i1 %t32 to i8
  store i8 %t33, ptr %l12
  %t34 = load i8, ptr %l12
  %t35 = icmp ne i8 %t34, 0
  br i1 %t35, label %bb12, label %bb13
bb12:
  store i32 5, ptr %l13
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l13, i64 4, i1 false)
  br label %bb1
bb13:
  %t36 = load i64, ptr %l1
  %t37 = load i64, ptr @"static std.systemerror.TAG_CONNECTION_ABORTED"
  %t38 = icmp eq i64 %t36, %t37
  %t39 = zext i1 %t38 to i8
  store i8 %t39, ptr %l14
  %t40 = load i8, ptr %l14
  %t41 = icmp ne i8 %t40, 0
  br i1 %t41, label %bb14, label %bb15
bb14:
  store i32 6, ptr %l15
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l15, i64 4, i1 false)
  br label %bb1
bb15:
  %t42 = load i64, ptr %l1
  %t43 = load i64, ptr @"static std.systemerror.TAG_BROKEN_PIPE"
  %t44 = icmp eq i64 %t42, %t43
  %t45 = zext i1 %t44 to i8
  store i8 %t45, ptr %l16
  %t46 = load i8, ptr %l16
  %t47 = icmp ne i8 %t46, 0
  br i1 %t47, label %bb16, label %bb17
bb16:
  store i32 7, ptr %l17
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l17, i64 4, i1 false)
  br label %bb1
bb17:
  %t48 = load i64, ptr %l1
  %t49 = load i64, ptr @"static std.systemerror.TAG_NOT_CONNECTED"
  %t50 = icmp eq i64 %t48, %t49
  %t51 = zext i1 %t50 to i8
  store i8 %t51, ptr %l18
  %t52 = load i8, ptr %l18
  %t53 = icmp ne i8 %t52, 0
  br i1 %t53, label %bb18, label %bb19
bb18:
  store i32 8, ptr %l19
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l19, i64 4, i1 false)
  br label %bb1
bb19:
  %t54 = load i64, ptr %l1
  %t55 = load i64, ptr @"static std.systemerror.TAG_NOT_FOUND"
  %t56 = icmp eq i64 %t54, %t55
  %t57 = zext i1 %t56 to i8
  store i8 %t57, ptr %l20
  %t58 = load i8, ptr %l20
  %t59 = icmp ne i8 %t58, 0
  br i1 %t59, label %bb20, label %bb21
bb20:
  store i32 9, ptr %l21
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l21, i64 4, i1 false)
  br label %bb1
bb21:
  %t60 = load i64, ptr %l1
  %t61 = load i64, ptr @"static std.systemerror.TAG_PERMISSION_DENIED"
  %t62 = icmp eq i64 %t60, %t61
  %t63 = zext i1 %t62 to i8
  store i8 %t63, ptr %l22
  %t64 = load i8, ptr %l22
  %t65 = icmp ne i8 %t64, 0
  br i1 %t65, label %bb22, label %bb23
bb22:
  store i32 10, ptr %l23
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l23, i64 4, i1 false)
  br label %bb1
bb23:
  %t66 = load i64, ptr %l1
  %t67 = load i64, ptr @"static std.systemerror.TAG_ALREADY_EXISTS"
  %t68 = icmp eq i64 %t66, %t67
  %t69 = zext i1 %t68 to i8
  store i8 %t69, ptr %l24
  %t70 = load i8, ptr %l24
  %t71 = icmp ne i8 %t70, 0
  br i1 %t71, label %bb24, label %bb25
bb24:
  store i32 11, ptr %l25
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l25, i64 4, i1 false)
  br label %bb1
bb25:
  %t72 = load i64, ptr %l1
  %t73 = load i64, ptr @"static std.systemerror.TAG_ADDRESS_IN_USE"
  %t74 = icmp eq i64 %t72, %t73
  %t75 = zext i1 %t74 to i8
  store i8 %t75, ptr %l26
  %t76 = load i8, ptr %l26
  %t77 = icmp ne i8 %t76, 0
  br i1 %t77, label %bb26, label %bb27
bb26:
  store i32 12, ptr %l27
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l27, i64 4, i1 false)
  br label %bb1
bb27:
  %t78 = load i64, ptr %l1
  %t79 = load i64, ptr @"static std.systemerror.TAG_INVALID_ARGUMENT"
  %t80 = icmp eq i64 %t78, %t79
  %t81 = zext i1 %t80 to i8
  store i8 %t81, ptr %l28
  %t82 = load i8, ptr %l28
  %t83 = icmp ne i8 %t82, 0
  br i1 %t83, label %bb28, label %bb29
bb28:
  store i32 13, ptr %l29
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l29, i64 4, i1 false)
  br label %bb1
bb29:
  %t84 = load i64, ptr %l1
  %t85 = load i64, ptr @"static std.systemerror.TAG_RESOURCES_EXHAUSTED"
  %t86 = icmp eq i64 %t84, %t85
  %t87 = zext i1 %t86 to i8
  store i8 %t87, ptr %l30
  %t88 = load i8, ptr %l30
  %t89 = icmp ne i8 %t88, 0
  br i1 %t89, label %bb30, label %bb31
bb30:
  store i32 14, ptr %l31
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l31, i64 4, i1 false)
  br label %bb1
bb31:
  %t90 = load i64, ptr %l1
  %t91 = load i64, ptr @"static std.systemerror.TAG_HOST_UNREACHABLE"
  %t92 = icmp eq i64 %t90, %t91
  %t93 = zext i1 %t92 to i8
  store i8 %t93, ptr %l32
  %t94 = load i8, ptr %l32
  %t95 = icmp ne i8 %t94, 0
  br i1 %t95, label %bb32, label %bb33
bb32:
  store i32 16, ptr %l33
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l33, i64 4, i1 false)
  br label %bb1
bb33:
  %t96 = load i64, ptr %l1
  %t97 = load i64, ptr @"static std.systemerror.TAG_NETWORK_UNREACHABLE"
  %t98 = icmp eq i64 %t96, %t97
  %t99 = zext i1 %t98 to i8
  store i8 %t99, ptr %l34
  %t100 = load i8, ptr %l34
  %t101 = icmp ne i8 %t100, 0
  br i1 %t101, label %bb34, label %bb35
bb34:
  store i32 17, ptr %l35
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l35, i64 4, i1 false)
  br label %bb1
bb35:
  %t102 = load i64, ptr %l1
  %t103 = load i64, ptr @"static std.systemerror.TAG_TIMED_OUT"
  %t104 = icmp eq i64 %t102, %t103
  %t105 = zext i1 %t104 to i8
  store i8 %t105, ptr %l36
  %t106 = load i8, ptr %l36
  %t107 = icmp ne i8 %t106, 0
  br i1 %t107, label %bb36, label %bb37
bb36:
  store i32 18, ptr %l37
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l37, i64 4, i1 false)
  br label %bb1
bb37:
  %t108 = load i64, ptr %l1
  %t109 = load i64, ptr @"static std.systemerror.TAG_HOST_DOWN"
  %t110 = icmp eq i64 %t108, %t109
  %t111 = zext i1 %t110 to i8
  store i8 %t111, ptr %l38
  %t112 = load i8, ptr %l38
  %t113 = icmp ne i8 %t112, 0
  br i1 %t113, label %bb38, label %bb39
bb38:
  store i32 19, ptr %l39
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l39, i64 4, i1 false)
  br label %bb1
bb39:
  %t114 = load i64, ptr %l1
  %t115 = load i64, ptr @"static std.systemerror.TAG_NETWORK_DOWN"
  %t116 = icmp eq i64 %t114, %t115
  %t117 = zext i1 %t116 to i8
  store i8 %t117, ptr %l40
  %t118 = load i8, ptr %l40
  %t119 = icmp ne i8 %t118, 0
  br i1 %t119, label %bb40, label %bb41
bb40:
  store i32 20, ptr %l41
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l41, i64 4, i1 false)
  br label %bb1
bb41:
  %t120 = load i64, ptr %l1
  %t121 = load i64, ptr @"static std.systemerror.TAG_INVALID_DESCRIPTOR"
  %t122 = icmp eq i64 %t120, %t121
  %t123 = zext i1 %t122 to i8
  store i8 %t123, ptr %l42
  %t124 = load i8, ptr %l42
  %t125 = icmp ne i8 %t124, 0
  br i1 %t125, label %bb42, label %bb43
bb42:
  store i32 21, ptr %l43
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l43, i64 4, i1 false)
  br label %bb1
bb43:
  %t126 = load i64, ptr %l1
  %t127 = load i64, ptr @"static std.systemerror.TAG_INPUT_OUTPUT_FAILED"
  %t128 = icmp eq i64 %t126, %t127
  %t129 = zext i1 %t128 to i8
  store i8 %t129, ptr %l44
  %t130 = load i8, ptr %l44
  %t131 = icmp ne i8 %t130, 0
  br i1 %t131, label %bb44, label %bb45
bb44:
  store i32 22, ptr %l45
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l45, i64 4, i1 false)
  br label %bb1
bb45:
  store i32 15, ptr %l46
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l46, i64 4, i1 false)
  br label %bb1
}

define internal void @"saw drop glue String"(ptr noalias %p1) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  store ptr %t0, ptr %l2
  %t1 = load ptr, ptr %l2
  call void @"saw std.string.String.deinit()"(ptr %t1)
  br label %bb1
bb1:
  ret void
}

define internal void @"saw std.stringbuilder.StringBuilder.append_text(s: &String)"(ptr %ret, ptr noalias %p1, ptr noalias %p2) #0 {
entry:
  %l0 = alloca [24 x i8], align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca ptr, align 8
  %l5 = alloca i64, align 8
  %l6 = alloca i8, align 1
  %l7 = alloca i64, align 8
  %l8 = alloca i64, align 8
  %l9 = alloca i64, align 8
  %l10 = alloca i64, align 8
  %l11 = alloca ptr, align 8
  %l12 = alloca i8, align 1
  %l13 = alloca i8, align 1
  %l14 = alloca ptr, align 8
  %l15 = alloca i64, align 8
  %l16 = alloca ptr, align 8
  %l17 = alloca i64, align 8
  %l18 = alloca ptr, align 8
  %l19 = alloca i64, align 8
  %l20 = alloca [16 x i8], align 8
  %l21 = alloca [24 x i8], align 8
  %l22 = alloca ptr, align 8
  %l23 = alloca i64, align 8
  %l24 = alloca i8, align 1
  %l25 = alloca i64, align 8
  %l26 = alloca i64, align 8
  %l27 = alloca ptr, align 8
  %l28 = alloca i8, align 1
  %l29 = alloca i8, align 1
  %l30 = alloca i64, align 8
  %l31 = alloca i64, align 8
  %l32 = alloca i64, align 8
  store ptr %p1, ptr %l1
  store ptr %p2, ptr %l2
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l2
  store ptr %t0, ptr %l4
  %t1 = load ptr, ptr %l4
  %t2 = call i64 @"saw std.string.String.len()"(ptr %t1)
  store i64 %t2, ptr %l5
  br label %bb1
bb1:
  %t3 = load i64, ptr %l5
  store i64 %t3, ptr %l3
  %t4 = load i64, ptr %l3
  %t5 = icmp eq i64 %t4, 0
  %t6 = zext i1 %t5 to i8
  store i8 %t6, ptr %l6
  %t7 = load i8, ptr %l6
  %t8 = icmp ne i8 %t7, 0
  br i1 %t8, label %bb3, label %bb4
bb2:
  %t9 = load ptr, ptr %l1
  %t10 = getelementptr i8, ptr %t9, i64 16
  %t11 = load i64, ptr %t10
  %t12 = load i64, ptr %l3
  %t13 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t11, i64 %t12)
  %t14 = extractvalue { i64, i1 } %t13, 0
  %t15 = extractvalue { i64, i1 } %t13, 1
  br i1 %t15, label %check.0, label %checked.1
check.0:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 113)
  unreachable
checked.1:
  store i64 %t14, ptr %l8
  %t16 = load i64, ptr %l8
  %t17 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t16, i64 1)
  %t18 = extractvalue { i64, i1 } %t17, 0
  %t19 = extractvalue { i64, i1 } %t17, 1
  br i1 %t19, label %check.2, label %checked.3
check.2:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 113)
  unreachable
checked.3:
  store i64 %t18, ptr %l9
  %t20 = load i64, ptr %l9
  store i64 %t20, ptr %l7
  %t21 = load i64, ptr %l7
  store i64 %t21, ptr %l10
  %t22 = load ptr, ptr %l1
  store ptr %t22, ptr %l11
  %t23 = load ptr, ptr %l11
  %t24 = load i64, ptr %l10
  %t25 = call i8 @"saw std.stringbuilder.StringBuilder.reserve_bytes(wanted: Int)"(ptr %t23, i64 %t24)
  store i8 %t25, ptr %l12
  br label %bb6
bb3:
  store i32 0, ptr %l0
  %t26 = getelementptr i8, ptr %l0, i64 8
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 24, i1 false)
  ret void
bb4:
  br label %bb2
bb5:
  %t27 = load ptr, ptr %l1
  %t28 = load i8, ptr %t27
  %t29 = zext i8 %t28 to i64
  switch i64 %t29, label %nocase.4 [ i64 1, label %bb15 i64 0, label %bb16 ]
nocase.4:
  unreachable
bb6:
  %t30 = load i8, ptr %l12
  %t31 = xor i8 %t30, 1
  store i8 %t31, ptr %l13
  %t32 = load i8, ptr %l13
  %t33 = icmp ne i8 %t32, 0
  br i1 %t33, label %bb7, label %bb8
bb7:
  %t34 = load ptr, ptr %l1
  %t35 = getelementptr i8, ptr %t34, i64 32
  %t36 = load i8, ptr %t35
  %t37 = icmp ne i8 %t36, 0
  br i1 %t37, label %bb10, label %bb11
bb8:
  br label %bb5
bb9:
  %t38 = load i64, ptr %l7
  store i64 %t38, ptr %l17
  %t39 = load ptr, ptr %l1
  store ptr %t39, ptr %l18
  %t40 = load ptr, ptr %l18
  %t41 = load i64, ptr %l17
  %t42 = call i64 @"saw std.stringbuilder.StringBuilder.grow_target(wanted: Int)"(ptr %t40, i64 %t41)
  store i64 %t42, ptr %l19
  br label %bb13
bb10:
  %t43 = load ptr, ptr %l2
  store ptr %t43, ptr %l14
  %t44 = load i64, ptr %l3
  store i64 %t44, ptr %l15
  %t45 = load ptr, ptr %l1
  store ptr %t45, ptr %l16
  %t46 = load ptr, ptr %l16
  %t47 = load ptr, ptr %l14
  %t48 = load i64, ptr %l15
  call void @"saw std.stringbuilder.StringBuilder.overflow(s: &String, n: Int)"(ptr %t46, ptr %t47, i64 %t48)
  br label %bb12
bb11:
  br label %bb9
bb12:
  store i32 0, ptr %l0
  %t49 = getelementptr i8, ptr %l0, i64 8
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 24, i1 false)
  ret void
bb13:
  %t50 = load i64, ptr %l19
  store i64 %t50, ptr %l20
  %t51 = getelementptr i8, ptr %l20, i64 8
  store i64 1, ptr %t51
  store i32 1, ptr %l21
  %t52 = getelementptr i8, ptr %l21, i64 8
  call void @llvm.memcpy.p0.p0.i64(ptr %t52, ptr %l20, i64 16, i1 false)
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l21, i64 24, i1 false)
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 24, i1 false)
  ret void
bb14:
  store i32 0, ptr %l0
  %t53 = getelementptr i8, ptr %l0, i64 8
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 24, i1 false)
  ret void
bb15:
  %t54 = load ptr, ptr %l1
  %t55 = getelementptr i8, ptr %t54, i64 8
  %t56 = load ptr, ptr %t55
  store ptr %t56, ptr %l22
  store i64 0, ptr %l23
  br label %bb17
bb16:
  br label %bb14
bb17:
  %t57 = load i64, ptr %l23
  %t58 = load i64, ptr %l3
  %t59 = icmp slt i64 %t57, %t58
  %t60 = zext i1 %t59 to i8
  store i8 %t60, ptr %l24
  %t61 = load i8, ptr %l24
  %t62 = icmp ne i8 %t61, 0
  br i1 %t62, label %bb19, label %bb18
bb18:
  %t63 = load ptr, ptr %l1
  %t64 = getelementptr i8, ptr %t63, i64 16
  %t65 = load i64, ptr %t64
  %t66 = load i64, ptr %l3
  %t67 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t65, i64 %t66)
  %t68 = extractvalue { i64, i1 } %t67, 0
  %t69 = extractvalue { i64, i1 } %t67, 1
  br i1 %t69, label %check.5, label %checked.6
check.5:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 127)
  unreachable
checked.6:
  store i64 %t68, ptr %l31
  %t70 = load ptr, ptr %l1
  %t71 = getelementptr i8, ptr %t70, i64 16
  %t72 = load i64, ptr %l31
  store i64 %t72, ptr %t71
  %t73 = load ptr, ptr %l1
  %t74 = getelementptr i8, ptr %t73, i64 16
  %t75 = load i64, ptr %t74
  store i64 %t75, ptr %l32
  %t76 = load ptr, ptr %l22
  %t77 = load i64, ptr %l32
  %t78 = mul i64 %t77, 1
  %t79 = getelementptr i8, ptr %t76, i64 %t78
  store i8 0, ptr %t79
  br label %bb14
bb19:
  br label %bb20
bb20:
  %t80 = load ptr, ptr %l1
  %t81 = getelementptr i8, ptr %t80, i64 16
  %t82 = load i64, ptr %t81
  %t83 = load i64, ptr %l23
  %t84 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t82, i64 %t83)
  %t85 = extractvalue { i64, i1 } %t84, 0
  %t86 = extractvalue { i64, i1 } %t84, 1
  br i1 %t86, label %check.7, label %checked.8
check.7:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 124)
  unreachable
checked.8:
  store i64 %t85, ptr %l25
  %t87 = load i64, ptr %l23
  store i64 %t87, ptr %l26
  %t88 = load ptr, ptr %l2
  store ptr %t88, ptr %l27
  %t89 = load ptr, ptr %l27
  %t90 = load i64, ptr %l26
  %t91 = call i8 @"saw std.string.String.byte_at(index: Int)"(ptr %t89, i64 %t90)
  store i8 %t91, ptr %l28
  br label %bb21
bb21:
  %t92 = load i8, ptr %l28
  store i8 %t92, ptr %l29
  %t93 = load ptr, ptr %l22
  %t94 = load i64, ptr %l25
  %t95 = mul i64 %t94, 1
  %t96 = getelementptr i8, ptr %t93, i64 %t95
  %t97 = load i8, ptr %l29
  store i8 %t97, ptr %t96
  %t98 = load i64, ptr %l23
  %t99 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t98, i64 1)
  %t100 = extractvalue { i64, i1 } %t99, 0
  %t101 = extractvalue { i64, i1 } %t99, 1
  br i1 %t101, label %check.9, label %checked.10
check.9:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 125)
  unreachable
checked.10:
  store i64 %t100, ptr %l30
  %t102 = load i64, ptr %l30
  store i64 %t102, ptr %l23
  br label %bb17
}

define internal void @"saw std.systemerror.SystemErrorKind.describe()"(ptr %ret, ptr noalias %p1) #0 {
entry:
  %l0 = alloca [8 x i8], align 8
  %l1 = alloca ptr, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = load i32, ptr %t0
  %t2 = zext i32 %t1 to i64
  switch i64 %t2, label %nocase.0 [ i64 0, label %bb2 i64 1, label %bb3 i64 2, label %bb4 i64 3, label %bb5 i64 4, label %bb6 i64 5, label %bb7 i64 6, label %bb8 i64 7, label %bb9 i64 8, label %bb10 i64 9, label %bb11 i64 10, label %bb12 i64 11, label %bb13 i64 12, label %bb14 i64 13, label %bb15 i64 14, label %bb16 i64 15, label %bb17 i64 16, label %bb18 i64 17, label %bb19 i64 18, label %bb20 i64 19, label %bb21 i64 20, label %bb22 i64 21, label %bb23 i64 22, label %bb24 i64 23, label %bb25 i64 24, label %bb26 ]
nocase.0:
  unreachable
bb1:
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 8, i1 false)
  ret void
bb2:
  br label %bb27
bb3:
  br label %bb28
bb4:
  br label %bb29
bb5:
  br label %bb30
bb6:
  br label %bb31
bb7:
  br label %bb32
bb8:
  br label %bb33
bb9:
  br label %bb34
bb10:
  br label %bb35
bb11:
  br label %bb36
bb12:
  br label %bb37
bb13:
  br label %bb38
bb14:
  br label %bb39
bb15:
  br label %bb40
bb16:
  br label %bb41
bb17:
  br label %bb42
bb18:
  br label %bb43
bb19:
  br label %bb44
bb20:
  br label %bb45
bb21:
  br label %bb46
bb22:
  br label %bb47
bb23:
  br label %bb48
bb24:
  br label %bb49
bb25:
  br label %bb50
bb26:
  br label %bb51
bb27:
  %t3 = getelementptr i8, ptr @.bytes.11, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t3)
  br label %bb1
bb28:
  %t4 = getelementptr i8, ptr @.bytes.12, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t4)
  br label %bb1
bb29:
  %t5 = getelementptr i8, ptr @.bytes.13, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t5)
  br label %bb1
bb30:
  %t6 = getelementptr i8, ptr @.bytes.14, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t6)
  br label %bb1
bb31:
  %t7 = getelementptr i8, ptr @.bytes.15, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t7)
  br label %bb1
bb32:
  %t8 = getelementptr i8, ptr @.bytes.16, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t8)
  br label %bb1
bb33:
  %t9 = getelementptr i8, ptr @.bytes.17, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t9)
  br label %bb1
bb34:
  %t10 = getelementptr i8, ptr @.bytes.18, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t10)
  br label %bb1
bb35:
  %t11 = getelementptr i8, ptr @.bytes.19, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t11)
  br label %bb1
bb36:
  %t12 = getelementptr i8, ptr @.bytes.20, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t12)
  br label %bb1
bb37:
  %t13 = getelementptr i8, ptr @.bytes.21, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t13)
  br label %bb1
bb38:
  %t14 = getelementptr i8, ptr @.bytes.22, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t14)
  br label %bb1
bb39:
  %t15 = getelementptr i8, ptr @.bytes.23, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t15)
  br label %bb1
bb40:
  %t16 = getelementptr i8, ptr @.bytes.24, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t16)
  br label %bb1
bb41:
  %t17 = getelementptr i8, ptr @.bytes.25, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t17)
  br label %bb1
bb42:
  %t18 = getelementptr i8, ptr @.bytes.26, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t18)
  br label %bb1
bb43:
  %t19 = getelementptr i8, ptr @.bytes.27, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t19)
  br label %bb1
bb44:
  %t20 = getelementptr i8, ptr @.bytes.28, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t20)
  br label %bb1
bb45:
  %t21 = getelementptr i8, ptr @.bytes.29, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t21)
  br label %bb1
bb46:
  %t22 = getelementptr i8, ptr @.bytes.30, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t22)
  br label %bb1
bb47:
  %t23 = getelementptr i8, ptr @.bytes.31, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t23)
  br label %bb1
bb48:
  %t24 = getelementptr i8, ptr @.bytes.32, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t24)
  br label %bb1
bb49:
  %t25 = getelementptr i8, ptr @.bytes.33, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t25)
  br label %bb1
bb50:
  %t26 = getelementptr i8, ptr @.bytes.34, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t26)
  br label %bb1
bb51:
  %t27 = getelementptr i8, ptr @.bytes.35, i64 16
  call void @"saw std.string.string_literal(bytes: UnsafePointer<Int8>)"(ptr %l0, ptr %t27)
  br label %bb1
}

define internal void @"saw std.stringbuilder.StringBuilder.append(value: Int)"(ptr %ret, ptr noalias %p1, i64 %p2) #0 {
entry:
  %l0 = alloca [24 x i8], align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca i64, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca ptr, align 8
  %l5 = alloca [24 x i8], align 8
  store ptr %p1, ptr %l1
  store i64 %p2, ptr %l2
  br label %bb0
bb0:
  %t0 = load i64, ptr %l2
  store i64 %t0, ptr %l3
  %t1 = load ptr, ptr %l1
  store ptr %t1, ptr %l4
  %t2 = load ptr, ptr %l4
  %t3 = load i64, ptr %l3
  call void @"saw std.stringbuilder.StringBuilder.append_decimal(value: Int)"(ptr %l5, ptr %t2, i64 %t3)
  br label %bb1
bb1:
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l5, i64 24, i1 false)
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 24, i1 false)
  ret void
}

define internal void @"saw std.stringbuilder.StringBuilder.deinit()"(ptr noalias %p1) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca [0 x i8], align 1
  %l4 = alloca ptr, align 8
  %l5 = alloca i64, align 8
  %l6 = alloca ptr, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = getelementptr i8, ptr %t0, i64 32
  %t2 = load i8, ptr %t1
  %t3 = icmp ne i8 %t2, 0
  br i1 %t3, label %bb2, label %bb3
bb1:
  %t4 = load ptr, ptr %l1
  %t5 = load i8, ptr %t4
  %t6 = zext i8 %t5 to i64
  switch i64 %t6, label %nocase.0 [ i64 1, label %bb5 i64 0, label %bb6 ]
nocase.0:
  unreachable
bb2:
  ret void
bb3:
  br label %bb1
bb4:
  ret void
bb5:
  %t7 = load ptr, ptr %l1
  %t8 = getelementptr i8, ptr %t7, i64 8
  %t9 = load ptr, ptr %t8
  store ptr %t9, ptr %l2
  %t10 = load ptr, ptr %l2
  store ptr %t10, ptr %l4
  %t11 = load ptr, ptr %l1
  %t12 = getelementptr i8, ptr %t11, i64 24
  %t13 = load i64, ptr %t12
  store i64 %t13, ptr %l5
  store ptr %l3, ptr %l6
  %t14 = load ptr, ptr %l6
  %t15 = load ptr, ptr %l4
  %t16 = load i64, ptr %l5
  call void @"saw std.alloc.GlobalAllocator.dealloc(ptr: UnsafePointer<Int8>, size: Int, align: Int)"(ptr %t14, ptr %t15, i64 %t16, i64 1)
  br label %bb7
bb6:
  br label %bb4
bb7:
  br label %bb4
}

define internal void @"saw std.string.String.deinit()"(ptr noalias %p1) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca ptr, align 8
  %l4 = alloca ptr, align 8
  %l5 = alloca i64, align 8
  %l6 = alloca ptr, align 8
  %l7 = alloca ptr, align 8
  %l8 = alloca i64, align 8
  %l9 = alloca i8, align 1
  %l10 = alloca i64, align 8
  %l11 = alloca i64, align 8
  %l12 = alloca i8, align 1
  %l13 = alloca i8, align 1
  %l14 = alloca i64, align 8
  %l15 = alloca i64, align 8
  %l16 = alloca i64, align 8
  %l17 = alloca i64, align 8
  %l18 = alloca ptr, align 8
  %l19 = alloca ptr, align 8
  %l20 = alloca ptr, align 8
  %l21 = alloca i64, align 8
  %l22 = alloca i64, align 8
  %l23 = alloca i64, align 8
  %l24 = alloca i64, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = load ptr, ptr %t0
  store ptr %t1, ptr %l3
  %t2 = load ptr, ptr %l3
  store ptr %t2, ptr %l2
  %t3 = load i64, ptr @"static std.string.REFCOUNT_SLOT"
  store i64 %t3, ptr %l5
  %t4 = load ptr, ptr %l2
  %t5 = load i64, ptr %l5
  %t6 = mul i64 %t5, 8
  %t7 = getelementptr i8, ptr %t4, i64 %t6
  store ptr %t7, ptr %l6
  %t8 = load ptr, ptr %l6
  store ptr %t8, ptr %l7
  %t9 = load ptr, ptr %l7
  store ptr %t9, ptr %l4
  %t10 = load ptr, ptr %l4
  %t11 = load atomic i64, ptr %t10 monotonic, align 8
  store i64 %t11, ptr %l8
  br label %bb2
bb1:
  %t12 = load ptr, ptr %l4
  %t13 = atomicrmw sub ptr %t12, i64 1 release
  store i64 %t13, ptr %l11
  br label %bb5
bb2:
  %t14 = load i64, ptr %l8
  %t15 = load i64, ptr @"static std.string.IMMORTAL"
  %t16 = icmp eq i64 %t14, %t15
  %t17 = zext i1 %t16 to i8
  store i8 %t17, ptr %l9
  %t18 = load i8, ptr %l9
  %t19 = icmp ne i8 %t18, 0
  br i1 %t19, label %bb3, label %bb4
bb3:
  ret void
bb4:
  br label %bb1
bb5:
  %t20 = load i64, ptr %l11
  store i64 %t20, ptr %l10
  %t21 = load i64, ptr %l10
  %t22 = icmp slt i64 %t21, 1
  %t23 = zext i1 %t22 to i8
  store i8 %t23, ptr %l12
  %t24 = load i8, ptr %l12
  %t25 = icmp ne i8 %t24, 0
  br i1 %t25, label %bb7, label %bb8
bb6:
  %t26 = load i64, ptr %l10
  %t27 = icmp eq i64 %t26, 1
  %t28 = zext i1 %t27 to i8
  store i8 %t28, ptr %l13
  %t29 = load i8, ptr %l13
  %t30 = icmp ne i8 %t29, 0
  br i1 %t30, label %bb10, label %bb11
bb7:
  call void @__saw_fail(ptr @.bytes.36, i64 10, i64 787, ptr @.bytes.37, i64 63)
  unreachable
  unreachable
bb8:
  br label %bb6
bb9:
  ret void
bb10:
  fence acquire
  br label %bb12
bb11:
  br label %bb9
bb12:
  %t31 = load i64, ptr @"static std.string.HEADER_WORDS"
  store i64 %t31, ptr %l15
  store i64 8, ptr %l16
  br label %bb13
bb13:
  %t32 = load i64, ptr %l15
  %t33 = load i64, ptr %l16
  %t34 = call { i64, i1 } @llvm.smul.with.overflow.i64(i64 %t32, i64 %t33)
  %t35 = extractvalue { i64, i1 } %t34, 0
  %t36 = extractvalue { i64, i1 } %t34, 1
  br i1 %t36, label %check.0, label %checked.1
check.0:
  call void @__saw_fail_overflow(ptr @.bytes.36, i64 10, i64 791)
  unreachable
checked.1:
  store i64 %t35, ptr %l17
  %t37 = load i64, ptr %l17
  store i64 %t37, ptr %l14
  %t38 = load ptr, ptr %l4
  store ptr %t38, ptr %l19
  %t39 = load ptr, ptr %l19
  store ptr %t39, ptr %l18
  %t40 = load ptr, ptr %l18
  store ptr %t40, ptr %l20
  %t41 = load i64, ptr %l14
  store i64 %t41, ptr %l21
  %t42 = load i64, ptr @"static std.string.LENGTH_SLOT"
  store i64 %t42, ptr %l22
  %t43 = load i64, ptr %l21
  %t44 = load ptr, ptr %l2
  %t45 = load i64, ptr %l22
  %t46 = mul i64 %t45, 8
  %t47 = getelementptr i8, ptr %t44, i64 %t46
  %t48 = load i64, ptr %t47
  %t49 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t43, i64 %t48)
  %t50 = extractvalue { i64, i1 } %t49, 0
  %t51 = extractvalue { i64, i1 } %t49, 1
  br i1 %t51, label %check.2, label %checked.3
check.2:
  call void @__saw_fail_overflow(ptr @.bytes.36, i64 10, i64 793)
  unreachable
checked.3:
  store i64 %t50, ptr %l23
  %t52 = load i64, ptr %l23
  %t53 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t52, i64 1)
  %t54 = extractvalue { i64, i1 } %t53, 0
  %t55 = extractvalue { i64, i1 } %t53, 1
  br i1 %t55, label %check.4, label %checked.5
check.4:
  call void @__saw_fail_overflow(ptr @.bytes.36, i64 10, i64 793)
  unreachable
checked.5:
  store i64 %t54, ptr %l24
  %t56 = load ptr, ptr %l20
  %t57 = load i64, ptr %l24
  %t58 = load i64, ptr @"static std.string.BLOCK_ALIGN"
  call void @__saw_rt_dealloc(ptr %t56, i64 %t57, i64 %t58)
  br label %bb14
bb14:
  br label %bb9
}

define internal i8 @"saw std.stringbuilder.StringBuilder.reserve_bytes(wanted: Int)"(ptr noalias %p1, i64 %p2) #0 {
entry:
  %l0 = alloca i8, align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca i64, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca i64, align 8
  %l5 = alloca i8, align 1
  %l6 = alloca i8, align 1
  %l7 = alloca i64, align 8
  %l8 = alloca i64, align 8
  %l9 = alloca ptr, align 8
  %l10 = alloca i64, align 8
  %l11 = alloca [0 x i8], align 1
  %l12 = alloca i64, align 8
  %l13 = alloca ptr, align 8
  %l14 = alloca [16 x i8], align 8
  %l15 = alloca ptr, align 8
  %l16 = alloca ptr, align 8
  %l17 = alloca [0 x i8], align 1
  %l18 = alloca ptr, align 8
  %l19 = alloca i64, align 8
  %l20 = alloca ptr, align 8
  %l21 = alloca i64, align 8
  %l22 = alloca [16 x i8], align 8
  store ptr %p1, ptr %l1
  store i64 %p2, ptr %l2
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = getelementptr i8, ptr %t0, i64 32
  %t2 = load i8, ptr %t1
  %t3 = icmp ne i8 %t2, 0
  br i1 %t3, label %bb2, label %bb3
bb1:
  %t4 = load ptr, ptr %l1
  %t5 = getelementptr i8, ptr %t4, i64 24
  %t6 = load i64, ptr %t5
  %t7 = load i64, ptr %l2
  %t8 = icmp sge i64 %t6, %t7
  %t9 = zext i1 %t8 to i8
  store i8 %t9, ptr %l6
  %t10 = load i8, ptr %l6
  %t11 = icmp ne i8 %t10, 0
  br i1 %t11, label %bb5, label %bb6
bb2:
  %t12 = load i64, ptr %l2
  store i64 %t12, ptr %l3
  %t13 = load ptr, ptr %l1
  %t14 = getelementptr i8, ptr %t13, i64 24
  %t15 = load i64, ptr %t14
  %t16 = load i64, ptr @"static std.stringbuilder.MARKER_LEN"
  %t17 = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %t15, i64 %t16)
  %t18 = extractvalue { i64, i1 } %t17, 0
  %t19 = extractvalue { i64, i1 } %t17, 1
  br i1 %t19, label %check.0, label %checked.1
check.0:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 356)
  unreachable
checked.1:
  store i64 %t18, ptr %l4
  %t20 = load i64, ptr %l3
  %t21 = load i64, ptr %l4
  %t22 = icmp sle i64 %t20, %t21
  %t23 = zext i1 %t22 to i8
  store i8 %t23, ptr %l5
  %t24 = load i8, ptr %l5
  store i8 %t24, ptr %l0
  %t25 = load i8, ptr %l0
  ret i8 %t25
bb3:
  br label %bb1
bb4:
  %t26 = load i64, ptr %l2
  store i64 %t26, ptr %l8
  %t27 = load ptr, ptr %l1
  store ptr %t27, ptr %l9
  %t28 = load ptr, ptr %l9
  %t29 = load i64, ptr %l8
  %t30 = call i64 @"saw std.stringbuilder.StringBuilder.grow_target(wanted: Int)"(ptr %t28, i64 %t29)
  store i64 %t30, ptr %l10
  br label %bb7
bb5:
  store i8 1, ptr %l0
  %t31 = load i8, ptr %l0
  ret i8 %t31
bb6:
  br label %bb4
bb7:
  %t32 = load i64, ptr %l10
  store i64 %t32, ptr %l7
  %t33 = load i64, ptr %l7
  store i64 %t33, ptr %l12
  store ptr %l11, ptr %l13
  %t34 = load ptr, ptr %l13
  %t35 = load i64, ptr %l12
  call void @"saw std.alloc.GlobalAllocator.alloc(size: Int, align: Int)"(ptr %l14, ptr %t34, i64 %t35, i64 1)
  br label %bb8
bb8:
  %t36 = load i8, ptr %l14
  %t37 = zext i8 %t36 to i64
  switch i64 %t37, label %nocase.2 [ i64 1, label %bb9 i64 0, label %bb10 ]
nocase.2:
  unreachable
bb9:
  %t38 = getelementptr i8, ptr %l14, i64 8
  %t39 = load ptr, ptr %t38
  store ptr %t39, ptr %l15
  %t40 = load ptr, ptr %l1
  %t41 = load i8, ptr %t40
  %t42 = zext i8 %t41 to i64
  switch i64 %t42, label %nocase.3 [ i64 1, label %bb12 i64 0, label %bb13 ]
nocase.3:
  unreachable
bb10:
  store i8 0, ptr %l0
  %t43 = load i8, ptr %l0
  ret i8 %t43
bb11:
  store i8 1, ptr %l22
  %t44 = getelementptr i8, ptr %l22, i64 8
  %t45 = load ptr, ptr %l15
  store ptr %t45, ptr %t44
  %t46 = load ptr, ptr %l1
  call void @llvm.memcpy.p0.p0.i64(ptr %t46, ptr %l22, i64 16, i1 false)
  %t47 = load ptr, ptr %l1
  %t48 = getelementptr i8, ptr %t47, i64 24
  %t49 = load i64, ptr %l7
  store i64 %t49, ptr %t48
  store i8 1, ptr %l0
  %t50 = load i8, ptr %l0
  ret i8 %t50
bb12:
  %t51 = load ptr, ptr %l1
  %t52 = getelementptr i8, ptr %t51, i64 8
  %t53 = load ptr, ptr %t52
  store ptr %t53, ptr %l16
  %t54 = load ptr, ptr %l16
  %t55 = load ptr, ptr %l15
  %t56 = load ptr, ptr %l1
  %t57 = getelementptr i8, ptr %t56, i64 16
  %t58 = load i64, ptr %t57
  call void @"saw std.mem.copy_bytes(source: UnsafePointer<Int8>, target: UnsafePointer<Int8>, count: Int)"(ptr %t54, ptr %t55, i64 %t58)
  br label %bb14
bb13:
  store i64 0, ptr %l21
  %t59 = load ptr, ptr %l15
  %t60 = load i64, ptr %l21
  %t61 = mul i64 %t60, 1
  %t62 = getelementptr i8, ptr %t59, i64 %t61
  store i8 0, ptr %t62
  br label %bb11
bb14:
  %t63 = load ptr, ptr %l16
  store ptr %t63, ptr %l18
  %t64 = load ptr, ptr %l1
  %t65 = getelementptr i8, ptr %t64, i64 24
  %t66 = load i64, ptr %t65
  store i64 %t66, ptr %l19
  store ptr %l17, ptr %l20
  %t67 = load ptr, ptr %l20
  %t68 = load ptr, ptr %l18
  %t69 = load i64, ptr %l19
  call void @"saw std.alloc.GlobalAllocator.dealloc(ptr: UnsafePointer<Int8>, size: Int, align: Int)"(ptr %t67, ptr %t68, i64 %t69, i64 1)
  br label %bb15
bb15:
  br label %bb11
}

define internal i64 @"saw std.stringbuilder.StringBuilder.grow_target(wanted: Int)"(ptr noalias %p1, i64 %p2) #0 {
entry:
  %l0 = alloca i64, align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca i64, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca i8, align 1
  %l5 = alloca i64, align 8
  %l6 = alloca i8, align 1
  store ptr %p1, ptr %l1
  store i64 %p2, ptr %l2
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = getelementptr i8, ptr %t0, i64 24
  %t2 = load i64, ptr %t1
  %t3 = icmp eq i64 %t2, 0
  %t4 = zext i1 %t3 to i8
  store i8 %t4, ptr %l4
  %t5 = load i8, ptr %l4
  %t6 = icmp ne i8 %t5, 0
  br i1 %t6, label %bb2, label %bb3
bb1:
  %t7 = load i64, ptr %l3
  %t8 = load i64, ptr %l2
  %t9 = icmp slt i64 %t7, %t8
  %t10 = zext i1 %t9 to i8
  store i8 %t10, ptr %l6
  %t11 = load i8, ptr %l6
  %t12 = icmp ne i8 %t11, 0
  br i1 %t12, label %bb5, label %bb6
bb2:
  %t13 = load i64, ptr @"static std.stringbuilder.FIRST_CAPACITY"
  store i64 %t13, ptr %l3
  br label %bb1
bb3:
  %t14 = load ptr, ptr %l1
  %t15 = getelementptr i8, ptr %t14, i64 24
  %t16 = load i64, ptr %t15
  %t17 = call { i64, i1 } @llvm.smul.with.overflow.i64(i64 %t16, i64 2)
  %t18 = extractvalue { i64, i1 } %t17, 0
  %t19 = extractvalue { i64, i1 } %t17, 1
  br i1 %t19, label %check.0, label %checked.1
check.0:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 343)
  unreachable
checked.1:
  store i64 %t18, ptr %l5
  %t20 = load i64, ptr %l5
  store i64 %t20, ptr %l3
  br label %bb1
bb4:
  %t21 = load i64, ptr %l0
  ret i64 %t21
bb5:
  %t22 = load i64, ptr %l2
  store i64 %t22, ptr %l0
  br label %bb4
bb6:
  %t23 = load i64, ptr %l3
  store i64 %t23, ptr %l0
  br label %bb4
}

define internal void @"saw std.stringbuilder.StringBuilder.overflow(s: &String, n: Int)"(ptr noalias %p1, ptr noalias %p2, i64 %p3) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca ptr, align 8
  %l5 = alloca i64, align 8
  %l6 = alloca i64, align 8
  %l7 = alloca i64, align 8
  %l8 = alloca i64, align 8
  %l9 = alloca i8, align 1
  %l10 = alloca i8, align 1
  %l11 = alloca i8, align 1
  %l12 = alloca i64, align 8
  %l13 = alloca ptr, align 8
  %l14 = alloca i8, align 1
  %l15 = alloca i64, align 8
  %l16 = alloca ptr, align 8
  %l17 = alloca i8, align 1
  %l18 = alloca i64, align 8
  %l19 = alloca i64, align 8
  %l20 = alloca i8, align 1
  %l21 = alloca i64, align 8
  %l22 = alloca i64, align 8
  %l23 = alloca ptr, align 8
  %l24 = alloca i8, align 1
  %l25 = alloca i8, align 1
  %l26 = alloca i64, align 8
  %l27 = alloca i64, align 8
  %l28 = alloca ptr, align 8
  store ptr %p1, ptr %l1
  store ptr %p2, ptr %l2
  store i64 %p3, ptr %l3
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = getelementptr i8, ptr %t0, i64 33
  %t2 = load i8, ptr %t1
  %t3 = icmp ne i8 %t2, 0
  br i1 %t3, label %bb2, label %bb3
bb1:
  %t4 = load ptr, ptr %l1
  %t5 = load i8, ptr %t4
  %t6 = zext i8 %t5 to i64
  switch i64 %t6, label %nocase.0 [ i64 1, label %bb5 i64 0, label %bb6 ]
nocase.0:
  unreachable
bb2:
  ret void
bb3:
  br label %bb1
bb4:
  %t7 = load ptr, ptr %l1
  store ptr %t7, ptr %l28
  %t8 = load ptr, ptr %l28
  call void @"saw std.stringbuilder.StringBuilder.mark_truncated()"(ptr %t8)
  br label %bb24
bb5:
  %t9 = load ptr, ptr %l1
  %t10 = getelementptr i8, ptr %t9, i64 8
  %t11 = load ptr, ptr %t10
  store ptr %t11, ptr %l4
  %t12 = load ptr, ptr %l1
  %t13 = getelementptr i8, ptr %t12, i64 24
  %t14 = load i64, ptr %t13
  %t15 = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %t14, i64 1)
  %t16 = extractvalue { i64, i1 } %t15, 0
  %t17 = extractvalue { i64, i1 } %t15, 1
  br i1 %t17, label %check.1, label %checked.2
check.1:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 303)
  unreachable
checked.2:
  store i64 %t16, ptr %l6
  %t18 = load i64, ptr %l6
  %t19 = load i64, ptr @"static std.stringbuilder.MARKER_LEN"
  %t20 = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %t18, i64 %t19)
  %t21 = extractvalue { i64, i1 } %t20, 0
  %t22 = extractvalue { i64, i1 } %t20, 1
  br i1 %t22, label %check.3, label %checked.4
check.3:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 303)
  unreachable
checked.4:
  store i64 %t21, ptr %l7
  %t23 = load i64, ptr %l7
  %t24 = load ptr, ptr %l1
  %t25 = getelementptr i8, ptr %t24, i64 16
  %t26 = load i64, ptr %t25
  %t27 = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %t23, i64 %t26)
  %t28 = extractvalue { i64, i1 } %t27, 0
  %t29 = extractvalue { i64, i1 } %t27, 1
  br i1 %t29, label %check.5, label %checked.6
check.5:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 303)
  unreachable
checked.6:
  store i64 %t28, ptr %l8
  %t30 = load i64, ptr %l8
  store i64 %t30, ptr %l5
  %t31 = load i64, ptr %l5
  %t32 = load i64, ptr %l3
  %t33 = icmp sgt i64 %t31, %t32
  %t34 = zext i1 %t33 to i8
  store i8 %t34, ptr %l9
  %t35 = load i8, ptr %l9
  %t36 = icmp ne i8 %t35, 0
  br i1 %t36, label %bb8, label %bb9
bb6:
  br label %bb4
bb7:
  br label %bb10
bb8:
  %t37 = load i64, ptr %l3
  store i64 %t37, ptr %l5
  br label %bb7
bb9:
  br label %bb7
bb10:
  %t38 = load i64, ptr %l5
  %t39 = icmp sgt i64 %t38, 0
  %t40 = zext i1 %t39 to i8
  store i8 %t40, ptr %l11
  %t41 = load i8, ptr %l11
  %t42 = icmp ne i8 %t41, 0
  br i1 %t42, label %bb13, label %bb14
bb11:
  store i64 0, ptr %l19
  br label %bb19
bb12:
  %t43 = load i8, ptr %l10
  %t44 = icmp ne i8 %t43, 0
  br i1 %t44, label %bb17, label %bb11
bb13:
  %t45 = load i64, ptr %l5
  store i64 %t45, ptr %l12
  %t46 = load ptr, ptr %l2
  store ptr %t46, ptr %l13
  %t47 = load ptr, ptr %l13
  %t48 = load i64, ptr %l12
  %t49 = call i8 @"saw std.string.String.byte_at(index: Int)"(ptr %t47, i64 %t48)
  store i8 %t49, ptr %l14
  br label %bb15
bb14:
  store i8 0, ptr %l10
  br label %bb12
bb15:
  %t50 = load i8, ptr %l14
  %t51 = zext i8 %t50 to i64
  %t52 = trunc i64 %t51 to i8
  %t53 = icmp eq i8 %t52, %t50
  %t54 = icmp sge i64 %t51, 0
  %t55 = and i1 %t53, %t54
  %t56 = zext i8 %t50 to i64
  store i64 %t56, ptr %l15
  %t57 = load ptr, ptr %l1
  store ptr %t57, ptr %l16
  %t58 = load ptr, ptr %l16
  %t59 = load i64, ptr %l15
  %t60 = call i8 @"saw std.stringbuilder.StringBuilder.is_continuation(b: Int)"(ptr %t58, i64 %t59)
  store i8 %t60, ptr %l17
  br label %bb16
bb16:
  %t61 = load i8, ptr %l17
  store i8 %t61, ptr %l10
  br label %bb12
bb17:
  br label %bb18
bb18:
  %t62 = load i64, ptr %l5
  %t63 = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %t62, i64 1)
  %t64 = extractvalue { i64, i1 } %t63, 0
  %t65 = extractvalue { i64, i1 } %t63, 1
  br i1 %t65, label %check.7, label %checked.8
check.7:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 308)
  unreachable
checked.8:
  store i64 %t64, ptr %l18
  %t66 = load i64, ptr %l18
  store i64 %t66, ptr %l5
  br label %bb10
bb19:
  %t67 = load i64, ptr %l19
  %t68 = load i64, ptr %l5
  %t69 = icmp slt i64 %t67, %t68
  %t70 = zext i1 %t69 to i8
  store i8 %t70, ptr %l20
  %t71 = load i8, ptr %l20
  %t72 = icmp ne i8 %t71, 0
  br i1 %t72, label %bb21, label %bb20
bb20:
  %t73 = load ptr, ptr %l1
  %t74 = getelementptr i8, ptr %t73, i64 16
  %t75 = load i64, ptr %t74
  %t76 = load i64, ptr %l5
  %t77 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t75, i64 %t76)
  %t78 = extractvalue { i64, i1 } %t77, 0
  %t79 = extractvalue { i64, i1 } %t77, 1
  br i1 %t79, label %check.9, label %checked.10
check.9:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 315)
  unreachable
checked.10:
  store i64 %t78, ptr %l27
  %t80 = load ptr, ptr %l1
  %t81 = getelementptr i8, ptr %t80, i64 16
  %t82 = load i64, ptr %l27
  store i64 %t82, ptr %t81
  br label %bb4
bb21:
  br label %bb22
bb22:
  %t83 = load ptr, ptr %l1
  %t84 = getelementptr i8, ptr %t83, i64 16
  %t85 = load i64, ptr %t84
  %t86 = load i64, ptr %l19
  %t87 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t85, i64 %t86)
  %t88 = extractvalue { i64, i1 } %t87, 0
  %t89 = extractvalue { i64, i1 } %t87, 1
  br i1 %t89, label %check.11, label %checked.12
check.11:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 312)
  unreachable
checked.12:
  store i64 %t88, ptr %l21
  %t90 = load i64, ptr %l19
  store i64 %t90, ptr %l22
  %t91 = load ptr, ptr %l2
  store ptr %t91, ptr %l23
  %t92 = load ptr, ptr %l23
  %t93 = load i64, ptr %l22
  %t94 = call i8 @"saw std.string.String.byte_at(index: Int)"(ptr %t92, i64 %t93)
  store i8 %t94, ptr %l24
  br label %bb23
bb23:
  %t95 = load i8, ptr %l24
  store i8 %t95, ptr %l25
  %t96 = load ptr, ptr %l4
  %t97 = load i64, ptr %l21
  %t98 = mul i64 %t97, 1
  %t99 = getelementptr i8, ptr %t96, i64 %t98
  %t100 = load i8, ptr %l25
  store i8 %t100, ptr %t99
  %t101 = load i64, ptr %l19
  %t102 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t101, i64 1)
  %t103 = extractvalue { i64, i1 } %t102, 0
  %t104 = extractvalue { i64, i1 } %t102, 1
  br i1 %t104, label %check.13, label %checked.14
check.13:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 313)
  unreachable
checked.14:
  store i64 %t103, ptr %l26
  %t105 = load i64, ptr %l26
  store i64 %t105, ptr %l19
  br label %bb19
bb24:
  ret void
}

define internal i8 @"saw std.string.String.byte_at(index: Int)"(ptr noalias %p1, i64 %p2) #0 {
entry:
  %l0 = alloca i8, align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca i64, align 8
  %l3 = alloca i8, align 1
  %l4 = alloca i8, align 1
  %l5 = alloca i64, align 8
  %l6 = alloca ptr, align 8
  %l7 = alloca i64, align 8
  %l8 = alloca i8, align 1
  %l9 = alloca i64, align 8
  %l10 = alloca ptr, align 8
  %l11 = alloca i64, align 8
  %l12 = alloca i64, align 8
  %l13 = alloca i8, align 1
  %l14 = alloca i8, align 1
  %t32 = alloca [120 x i8], align 8
  store ptr %p1, ptr %l1
  store i64 %p2, ptr %l2
  br label %bb0
bb0:
  %t0 = load i64, ptr %l2
  %t1 = icmp slt i64 %t0, 0
  %t2 = zext i1 %t1 to i8
  store i8 %t2, ptr %l4
  %t3 = load i8, ptr %l4
  %t4 = icmp ne i8 %t3, 0
  br i1 %t4, label %bb4, label %bb3
bb1:
  %t5 = load i64, ptr %l2
  store i64 %t5, ptr %l12
  %t6 = load ptr, ptr %l1
  %t7 = load ptr, ptr %t6
  %t8 = load i64, ptr %l12
  %t9 = mul i64 %t8, 1
  %t10 = getelementptr i8, ptr %t7, i64 %t9
  %t11 = load i8, ptr %t10
  store i8 %t11, ptr %l13
  %t12 = load i8, ptr %l13
  store i8 %t12, ptr %l14
  %t13 = load i8, ptr %l14
  store i8 %t13, ptr %l0
  %t14 = load i8, ptr %l0
  ret i8 %t14
bb2:
  %t15 = load i8, ptr %l3
  %t16 = icmp ne i8 %t15, 0
  br i1 %t16, label %bb6, label %bb7
bb3:
  %t17 = load i64, ptr %l2
  store i64 %t17, ptr %l5
  %t18 = load ptr, ptr %l1
  store ptr %t18, ptr %l6
  %t19 = load ptr, ptr %l6
  %t20 = call i64 @"saw std.string.String.len()"(ptr %t19)
  store i64 %t20, ptr %l7
  br label %bb5
bb4:
  store i8 1, ptr %l3
  br label %bb2
bb5:
  %t21 = load i64, ptr %l5
  %t22 = load i64, ptr %l7
  %t23 = icmp sge i64 %t21, %t22
  %t24 = zext i1 %t23 to i8
  store i8 %t24, ptr %l8
  %t25 = load i8, ptr %l8
  store i8 %t25, ptr %l3
  br label %bb2
bb6:
  %t26 = load i64, ptr %l2
  store i64 %t26, ptr %l9
  %t27 = load ptr, ptr %l1
  store ptr %t27, ptr %l10
  %t28 = load ptr, ptr %l10
  %t29 = call i64 @"saw std.string.String.len()"(ptr %t28)
  store i64 %t29, ptr %l11
  br label %bb8
bb7:
  br label %bb1
bb8:
  %t30 = load i64, ptr %l9
  %t31 = load i64, ptr %l11
  store i64 0, ptr %t32
  %t33 = getelementptr i8, ptr %t32, i64 8
  store ptr @.bytes.38, ptr %t33
  %t34 = getelementptr i8, ptr %t32, i64 16
  store i64 36, ptr %t34
  %t35 = getelementptr i8, ptr %t32, i64 24
  store i64 1, ptr %t35
  %t36 = getelementptr i8, ptr %t32, i64 32
  store i64 %t30, ptr %t36
  %t37 = getelementptr i8, ptr %t32, i64 48
  store i64 0, ptr %t37
  %t38 = getelementptr i8, ptr %t32, i64 56
  store ptr @.bytes.39, ptr %t38
  %t39 = getelementptr i8, ptr %t32, i64 64
  store i64 6, ptr %t39
  %t40 = getelementptr i8, ptr %t32, i64 72
  store i64 1, ptr %t40
  %t41 = getelementptr i8, ptr %t32, i64 80
  store i64 %t31, ptr %t41
  %t42 = getelementptr i8, ptr %t32, i64 96
  store i64 0, ptr %t42
  %t43 = getelementptr i8, ptr %t32, i64 104
  store ptr @.bytes.40, ptr %t43
  %t44 = getelementptr i8, ptr %t32, i64 112
  store i64 1, ptr %t44
  call void @__saw_fail_parts(ptr @.bytes.36, i64 10, i64 234, ptr @.bytes.41, i64 0, ptr %t32, i64 5)
  unreachable
  unreachable
}

define internal void @"saw std.stringbuilder.StringBuilder.append_decimal(value: Int)"(ptr %ret, ptr noalias %p1, i64 %p2) #0 {
entry:
  %l0 = alloca [24 x i8], align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca i64, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca i8, align 1
  %l5 = alloca i64, align 8
  %l6 = alloca i64, align 8
  %l7 = alloca i64, align 8
  %l8 = alloca i64, align 8
  %l9 = alloca i64, align 8
  %l10 = alloca i8, align 1
  %l11 = alloca i64, align 8
  %l12 = alloca i64, align 8
  %l13 = alloca i64, align 8
  %l14 = alloca i64, align 8
  %l15 = alloca i8, align 1
  %l16 = alloca i64, align 8
  %l17 = alloca i64, align 8
  %l18 = alloca i64, align 8
  %l19 = alloca i64, align 8
  %l20 = alloca i8, align 1
  %l21 = alloca i64, align 8
  %l22 = alloca ptr, align 8
  %l23 = alloca i8, align 1
  %l24 = alloca i8, align 1
  %l25 = alloca i8, align 1
  %l26 = alloca i64, align 8
  %l27 = alloca ptr, align 8
  %l28 = alloca i64, align 8
  %l29 = alloca [16 x i8], align 8
  %l30 = alloca [24 x i8], align 8
  %l31 = alloca i8, align 1
  %l32 = alloca i64, align 8
  %l33 = alloca ptr, align 8
  %l34 = alloca i8, align 1
  %l35 = alloca i64, align 8
  %l36 = alloca i64, align 8
  %l37 = alloca i64, align 8
  %l38 = alloca i64, align 8
  %l39 = alloca i64, align 8
  %l40 = alloca ptr, align 8
  %l41 = alloca i64, align 8
  store ptr %p1, ptr %l1
  store i64 %p2, ptr %l2
  br label %bb0
bb0:
  %t0 = load i64, ptr %l2
  %t1 = icmp slt i64 %t0, 0
  %t2 = zext i1 %t1 to i8
  store i8 %t2, ptr %l4
  %t3 = load i8, ptr %l4
  %t4 = icmp ne i8 %t3, 0
  br i1 %t4, label %bb2, label %bb3
bb1:
  store i64 1, ptr %l6
  store i64 1, ptr %l7
  %t5 = load i64, ptr %l3
  store i64 %t5, ptr %l8
  br label %bb4
bb2:
  %t6 = load i64, ptr %l2
  store i64 %t6, ptr %l3
  br label %bb1
bb3:
  %t7 = load i64, ptr %l2
  %t8 = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 0, i64 %t7)
  %t9 = extractvalue { i64, i1 } %t8, 0
  %t10 = extractvalue { i64, i1 } %t8, 1
  br i1 %t10, label %check.0, label %checked.1
check.0:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 168)
  unreachable
checked.1:
  store i64 %t9, ptr %l5
  %t11 = load i64, ptr %l5
  store i64 %t11, ptr %l3
  br label %bb1
bb4:
  store i64 -10, ptr %l9
  %t12 = load i64, ptr %l8
  %t13 = load i64, ptr %l9
  %t14 = icmp sle i64 %t12, %t13
  %t15 = zext i1 %t14 to i8
  store i8 %t15, ptr %l10
  %t16 = load i8, ptr %l10
  %t17 = icmp ne i8 %t16, 0
  br i1 %t17, label %bb6, label %bb5
bb5:
  %t18 = load i64, ptr %l2
  %t19 = icmp slt i64 %t18, 0
  %t20 = zext i1 %t19 to i8
  store i8 %t20, ptr %l15
  %t21 = load i8, ptr %l15
  %t22 = icmp ne i8 %t21, 0
  br i1 %t22, label %bb9, label %bb10
bb6:
  br label %bb7
bb7:
  %t23 = load i64, ptr %l8
  %t24 = icmp eq i64 10, 0
  br i1 %t24, label %check.2, label %checked.3
check.2:
  call void @__saw_fail_divide(ptr @.bytes.5, i64 17, i64 173)
  unreachable
checked.3:
  %t25 = icmp eq i64 %t23, -9223372036854775808
  %t26 = icmp eq i64 10, -1
  %t27 = and i1 %t25, %t26
  br i1 %t27, label %check.4, label %checked.5
check.4:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 173)
  unreachable
checked.5:
  %t28 = sdiv i64 %t23, 10
  store i64 %t28, ptr %l11
  %t29 = load i64, ptr %l11
  store i64 %t29, ptr %l8
  %t30 = load i64, ptr %l7
  %t31 = call { i64, i1 } @llvm.smul.with.overflow.i64(i64 %t30, i64 10)
  %t32 = extractvalue { i64, i1 } %t31, 0
  %t33 = extractvalue { i64, i1 } %t31, 1
  br i1 %t33, label %check.6, label %checked.7
check.6:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 174)
  unreachable
checked.7:
  store i64 %t32, ptr %l12
  %t34 = load i64, ptr %l12
  store i64 %t34, ptr %l7
  %t35 = load i64, ptr %l6
  %t36 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t35, i64 1)
  %t37 = extractvalue { i64, i1 } %t36, 0
  %t38 = extractvalue { i64, i1 } %t36, 1
  br i1 %t38, label %check.8, label %checked.9
check.8:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 175)
  unreachable
checked.9:
  store i64 %t37, ptr %l13
  %t39 = load i64, ptr %l13
  store i64 %t39, ptr %l6
  br label %bb4
bb8:
  %t40 = load ptr, ptr %l1
  %t41 = getelementptr i8, ptr %t40, i64 16
  %t42 = load i64, ptr %t41
  %t43 = load i64, ptr %l14
  %t44 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t42, i64 %t43)
  %t45 = extractvalue { i64, i1 } %t44, 0
  %t46 = extractvalue { i64, i1 } %t44, 1
  br i1 %t46, label %check.10, label %checked.11
check.10:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 178)
  unreachable
checked.11:
  store i64 %t45, ptr %l17
  %t47 = load i64, ptr %l17
  %t48 = load i64, ptr %l6
  %t49 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t47, i64 %t48)
  %t50 = extractvalue { i64, i1 } %t49, 0
  %t51 = extractvalue { i64, i1 } %t49, 1
  br i1 %t51, label %check.12, label %checked.13
check.12:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 178)
  unreachable
checked.13:
  store i64 %t50, ptr %l18
  %t52 = load i64, ptr %l18
  %t53 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t52, i64 1)
  %t54 = extractvalue { i64, i1 } %t53, 0
  %t55 = extractvalue { i64, i1 } %t53, 1
  br i1 %t55, label %check.14, label %checked.15
check.14:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 178)
  unreachable
checked.15:
  store i64 %t54, ptr %l19
  %t56 = load i64, ptr %l19
  store i64 %t56, ptr %l16
  %t57 = load i64, ptr %l16
  store i64 %t57, ptr %l21
  %t58 = load ptr, ptr %l1
  store ptr %t58, ptr %l22
  %t59 = load ptr, ptr %l22
  %t60 = load i64, ptr %l21
  %t61 = call i8 @"saw std.stringbuilder.StringBuilder.reserve_bytes(wanted: Int)"(ptr %t59, i64 %t60)
  store i8 %t61, ptr %l23
  br label %bb13
bb9:
  store i64 1, ptr %l14
  br label %bb8
bb10:
  store i64 0, ptr %l14
  br label %bb8
bb11:
  %t62 = load i64, ptr %l2
  %t63 = icmp slt i64 %t62, 0
  %t64 = zext i1 %t63 to i8
  store i8 %t64, ptr %l31
  %t65 = load i8, ptr %l31
  %t66 = icmp ne i8 %t65, 0
  br i1 %t66, label %bb20, label %bb21
bb12:
  %t67 = load i8, ptr %l20
  %t68 = icmp ne i8 %t67, 0
  br i1 %t68, label %bb16, label %bb17
bb13:
  %t69 = load i8, ptr %l23
  %t70 = xor i8 %t69, 1
  store i8 %t70, ptr %l24
  %t71 = load i8, ptr %l24
  %t72 = icmp ne i8 %t71, 0
  br i1 %t72, label %bb14, label %bb15
bb14:
  %t73 = load ptr, ptr %l1
  %t74 = getelementptr i8, ptr %t73, i64 32
  %t75 = load i8, ptr %t74
  %t76 = xor i8 %t75, 1
  store i8 %t76, ptr %l25
  %t77 = load i8, ptr %l25
  store i8 %t77, ptr %l20
  br label %bb12
bb15:
  store i8 0, ptr %l20
  br label %bb12
bb16:
  %t78 = load i64, ptr %l16
  store i64 %t78, ptr %l26
  %t79 = load ptr, ptr %l1
  store ptr %t79, ptr %l27
  %t80 = load ptr, ptr %l27
  %t81 = load i64, ptr %l26
  %t82 = call i64 @"saw std.stringbuilder.StringBuilder.grow_target(wanted: Int)"(ptr %t80, i64 %t81)
  store i64 %t82, ptr %l28
  br label %bb18
bb17:
  br label %bb11
bb18:
  %t83 = load i64, ptr %l28
  store i64 %t83, ptr %l29
  %t84 = getelementptr i8, ptr %l29, i64 8
  store i64 1, ptr %t84
  store i32 1, ptr %l30
  %t85 = getelementptr i8, ptr %l30, i64 8
  call void @llvm.memcpy.p0.p0.i64(ptr %t85, ptr %l29, i64 16, i1 false)
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l30, i64 24, i1 false)
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 24, i1 false)
  ret void
bb19:
  br label %bb23
bb20:
  %t86 = load i64, ptr @"static std.stringbuilder.MINUS_SIGN"
  store i64 %t86, ptr %l32
  %t87 = load ptr, ptr %l1
  store ptr %t87, ptr %l33
  %t88 = load ptr, ptr %l33
  %t89 = load i64, ptr %l32
  call void @"saw std.stringbuilder.StringBuilder.place_byte(b: Int)"(ptr %t88, i64 %t89)
  br label %bb22
bb21:
  br label %bb19
bb22:
  br label %bb19
bb23:
  %t90 = load i64, ptr %l7
  %t91 = icmp sgt i64 %t90, 0
  %t92 = zext i1 %t91 to i8
  store i8 %t92, ptr %l34
  %t93 = load i8, ptr %l34
  %t94 = icmp ne i8 %t93, 0
  br i1 %t94, label %bb25, label %bb24
bb24:
  store i32 0, ptr %l0
  %t95 = getelementptr i8, ptr %l0, i64 8
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 24, i1 false)
  ret void
bb25:
  br label %bb26
bb26:
  %t96 = load i64, ptr %l3
  %t97 = load i64, ptr %l7
  %t98 = icmp eq i64 %t97, 0
  br i1 %t98, label %check.16, label %checked.17
check.16:
  call void @__saw_fail_divide(ptr @.bytes.5, i64 17, i64 186)
  unreachable
checked.17:
  %t99 = icmp eq i64 %t96, -9223372036854775808
  %t100 = icmp eq i64 %t97, -1
  %t101 = and i1 %t99, %t100
  br i1 %t101, label %check.18, label %checked.19
check.18:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 186)
  unreachable
checked.19:
  %t102 = sdiv i64 %t96, %t97
  store i64 %t102, ptr %l36
  %t103 = load i64, ptr %l36
  %t104 = icmp eq i64 10, 0
  br i1 %t104, label %check.20, label %checked.21
check.20:
  call void @__saw_fail_divide(ptr @.bytes.5, i64 17, i64 186)
  unreachable
checked.21:
  %t105 = icmp eq i64 %t103, -9223372036854775808
  %t106 = icmp eq i64 10, -1
  %t107 = and i1 %t105, %t106
  br i1 %t107, label %check.22, label %checked.23
check.22:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 186)
  unreachable
checked.23:
  %t108 = srem i64 %t103, 10
  store i64 %t108, ptr %l37
  %t109 = load i64, ptr %l37
  %t110 = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 0, i64 %t109)
  %t111 = extractvalue { i64, i1 } %t110, 0
  %t112 = extractvalue { i64, i1 } %t110, 1
  br i1 %t112, label %check.24, label %checked.25
check.24:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 186)
  unreachable
checked.25:
  store i64 %t111, ptr %l38
  %t113 = load i64, ptr %l38
  store i64 %t113, ptr %l35
  %t114 = load i64, ptr @"static std.stringbuilder.ASCII_ZERO"
  %t115 = load i64, ptr %l35
  %t116 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t114, i64 %t115)
  %t117 = extractvalue { i64, i1 } %t116, 0
  %t118 = extractvalue { i64, i1 } %t116, 1
  br i1 %t118, label %check.26, label %checked.27
check.26:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 187)
  unreachable
checked.27:
  store i64 %t117, ptr %l39
  %t119 = load ptr, ptr %l1
  store ptr %t119, ptr %l40
  %t120 = load ptr, ptr %l40
  %t121 = load i64, ptr %l39
  call void @"saw std.stringbuilder.StringBuilder.place_byte(b: Int)"(ptr %t120, i64 %t121)
  br label %bb27
bb27:
  %t122 = load i64, ptr %l7
  %t123 = icmp eq i64 10, 0
  br i1 %t123, label %check.28, label %checked.29
check.28:
  call void @__saw_fail_divide(ptr @.bytes.5, i64 17, i64 188)
  unreachable
checked.29:
  %t124 = icmp eq i64 %t122, -9223372036854775808
  %t125 = icmp eq i64 10, -1
  %t126 = and i1 %t124, %t125
  br i1 %t126, label %check.30, label %checked.31
check.30:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 188)
  unreachable
checked.31:
  %t127 = sdiv i64 %t122, 10
  store i64 %t127, ptr %l41
  %t128 = load i64, ptr %l41
  store i64 %t128, ptr %l7
  br label %bb23
}

define internal void @"saw std.alloc.GlobalAllocator.dealloc(ptr: UnsafePointer<Int8>, size: Int, align: Int)"(ptr noalias %p1, ptr %p2, i64 %p3, i64 %p4) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca i64, align 8
  store ptr %p1, ptr %l1
  store ptr %p2, ptr %l2
  store i64 %p3, ptr %l3
  store i64 %p4, ptr %l4
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l2
  %t1 = load i64, ptr %l3
  %t2 = load i64, ptr %l4
  call void @__saw_rt_dealloc(ptr %t0, i64 %t1, i64 %t2)
  br label %bb1
bb1:
  ret void
}

define internal void @"saw std.alloc.GlobalAllocator.alloc(size: Int, align: Int)"(ptr %ret, ptr noalias %p1, i64 %p2, i64 %p3) #0 {
entry:
  %l0 = alloca [16 x i8], align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca i64, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca [16 x i8], align 8
  store ptr %p1, ptr %l1
  store i64 %p2, ptr %l2
  store i64 %p3, ptr %l3
  br label %bb0
bb0:
  %t0 = load i64, ptr %l2
  %t1 = load i64, ptr %l3
  %t2 = call ptr @__saw_rt_alloc(i64 %t0, i64 %t1)
  %t3 = icmp ne ptr %t2, null
  %t4 = zext i1 %t3 to i8
  store i8 %t4, ptr %l4
  %t5 = getelementptr i8, ptr %l4, i64 8
  store ptr %t2, ptr %t5
  br label %bb1
bb1:
  call void @llvm.memcpy.p0.p0.i64(ptr %l0, ptr %l4, i64 16, i1 false)
  call void @llvm.memcpy.p0.p0.i64(ptr %ret, ptr %l0, i64 16, i1 false)
  ret void
}

define internal void @"saw std.mem.copy_bytes(source: UnsafePointer<Int8>, target: UnsafePointer<Int8>, count: Int)"(ptr %p1, ptr %p2, i64 %p3) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca i64, align 8
  %l5 = alloca i8, align 1
  %l6 = alloca i64, align 8
  %l7 = alloca i64, align 8
  %l8 = alloca i64, align 8
  store ptr %p1, ptr %l1
  store ptr %p2, ptr %l2
  store i64 %p3, ptr %l3
  br label %bb0
bb0:
  store i64 0, ptr %l4
  br label %bb1
bb1:
  %t0 = load i64, ptr %l4
  %t1 = load i64, ptr %l3
  %t2 = icmp slt i64 %t0, %t1
  %t3 = zext i1 %t2 to i8
  store i8 %t3, ptr %l5
  %t4 = load i8, ptr %l5
  %t5 = icmp ne i8 %t4, 0
  br i1 %t5, label %bb3, label %bb2
bb2:
  ret void
bb3:
  br label %bb4
bb4:
  %t6 = load i64, ptr %l4
  store i64 %t6, ptr %l6
  %t7 = load i64, ptr %l4
  store i64 %t7, ptr %l7
  %t8 = load ptr, ptr %l2
  %t9 = load i64, ptr %l6
  %t10 = mul i64 %t9, 1
  %t11 = getelementptr i8, ptr %t8, i64 %t10
  %t12 = load ptr, ptr %l1
  %t13 = load i64, ptr %l7
  %t14 = mul i64 %t13, 1
  %t15 = getelementptr i8, ptr %t12, i64 %t14
  %t16 = load i8, ptr %t15
  store i8 %t16, ptr %t11
  %t17 = load i64, ptr %l4
  %t18 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t17, i64 1)
  %t19 = extractvalue { i64, i1 } %t18, 0
  %t20 = extractvalue { i64, i1 } %t18, 1
  br i1 %t20, label %check.0, label %checked.1
check.0:
  call void @__saw_fail_overflow(ptr @.bytes.42, i64 7, i64 18)
  unreachable
checked.1:
  store i64 %t19, ptr %l8
  %t21 = load i64, ptr %l8
  store i64 %t21, ptr %l4
  br label %bb1
}

define internal void @"saw std.stringbuilder.StringBuilder.mark_truncated()"(ptr noalias %p1) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  %l3 = alloca i64, align 8
  %l4 = alloca i8, align 1
  %l5 = alloca i64, align 8
  %l6 = alloca i8, align 1
  %l7 = alloca i64, align 8
  %l8 = alloca i8, align 1
  %l9 = alloca i64, align 8
  %l10 = alloca i64, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = getelementptr i8, ptr %t0, i64 33
  %t2 = load i8, ptr %t1
  %t3 = icmp ne i8 %t2, 0
  br i1 %t3, label %bb2, label %bb3
bb1:
  %t4 = load ptr, ptr %l1
  %t5 = getelementptr i8, ptr %t4, i64 33
  store i8 1, ptr %t5
  %t6 = load ptr, ptr %l1
  %t7 = load i8, ptr %t6
  %t8 = zext i8 %t7 to i64
  switch i64 %t8, label %nocase.0 [ i64 1, label %bb5 i64 0, label %bb6 ]
nocase.0:
  unreachable
bb2:
  ret void
bb3:
  br label %bb1
bb4:
  ret void
bb5:
  %t9 = load ptr, ptr %l1
  %t10 = getelementptr i8, ptr %t9, i64 8
  %t11 = load ptr, ptr %t10
  store ptr %t11, ptr %l2
  %t12 = load ptr, ptr %l1
  %t13 = getelementptr i8, ptr %t12, i64 16
  %t14 = load i64, ptr %t13
  store i64 %t14, ptr %l3
  %t15 = load i64, ptr @"static std.stringbuilder.MARKER_BYTE_0"
  %t16 = trunc i64 %t15 to i8
  store i8 %t16, ptr %l4
  %t17 = load ptr, ptr %l2
  %t18 = load i64, ptr %l3
  %t19 = mul i64 %t18, 1
  %t20 = getelementptr i8, ptr %t17, i64 %t19
  %t21 = load i8, ptr %l4
  store i8 %t21, ptr %t20
  %t22 = load ptr, ptr %l1
  %t23 = getelementptr i8, ptr %t22, i64 16
  %t24 = load i64, ptr %t23
  %t25 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t24, i64 1)
  %t26 = extractvalue { i64, i1 } %t25, 0
  %t27 = extractvalue { i64, i1 } %t25, 1
  br i1 %t27, label %check.1, label %checked.2
check.1:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 329)
  unreachable
checked.2:
  store i64 %t26, ptr %l5
  %t28 = load i64, ptr @"static std.stringbuilder.MARKER_BYTE_1"
  %t29 = trunc i64 %t28 to i8
  store i8 %t29, ptr %l6
  %t30 = load ptr, ptr %l2
  %t31 = load i64, ptr %l5
  %t32 = mul i64 %t31, 1
  %t33 = getelementptr i8, ptr %t30, i64 %t32
  %t34 = load i8, ptr %l6
  store i8 %t34, ptr %t33
  %t35 = load ptr, ptr %l1
  %t36 = getelementptr i8, ptr %t35, i64 16
  %t37 = load i64, ptr %t36
  %t38 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t37, i64 2)
  %t39 = extractvalue { i64, i1 } %t38, 0
  %t40 = extractvalue { i64, i1 } %t38, 1
  br i1 %t40, label %check.3, label %checked.4
check.3:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 330)
  unreachable
checked.4:
  store i64 %t39, ptr %l7
  %t41 = load i64, ptr @"static std.stringbuilder.MARKER_BYTE_2"
  %t42 = trunc i64 %t41 to i8
  store i8 %t42, ptr %l8
  %t43 = load ptr, ptr %l2
  %t44 = load i64, ptr %l7
  %t45 = mul i64 %t44, 1
  %t46 = getelementptr i8, ptr %t43, i64 %t45
  %t47 = load i8, ptr %l8
  store i8 %t47, ptr %t46
  %t48 = load ptr, ptr %l1
  %t49 = getelementptr i8, ptr %t48, i64 16
  %t50 = load i64, ptr %t49
  %t51 = load i64, ptr @"static std.stringbuilder.MARKER_LEN"
  %t52 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t50, i64 %t51)
  %t53 = extractvalue { i64, i1 } %t52, 0
  %t54 = extractvalue { i64, i1 } %t52, 1
  br i1 %t54, label %check.5, label %checked.6
check.5:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 331)
  unreachable
checked.6:
  store i64 %t53, ptr %l9
  %t55 = load ptr, ptr %l1
  %t56 = getelementptr i8, ptr %t55, i64 16
  %t57 = load i64, ptr %l9
  store i64 %t57, ptr %t56
  %t58 = load ptr, ptr %l1
  %t59 = getelementptr i8, ptr %t58, i64 16
  %t60 = load i64, ptr %t59
  store i64 %t60, ptr %l10
  %t61 = load ptr, ptr %l2
  %t62 = load i64, ptr %l10
  %t63 = mul i64 %t62, 1
  %t64 = getelementptr i8, ptr %t61, i64 %t63
  store i8 0, ptr %t64
  br label %bb4
bb6:
  br label %bb4
}

define internal i8 @"saw std.stringbuilder.StringBuilder.is_continuation(b: Int)"(ptr noalias %p1, i64 %p2) #0 {
entry:
  %l0 = alloca i8, align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca i64, align 8
  %l3 = alloca i8, align 1
  %l4 = alloca i8, align 1
  %l5 = alloca i8, align 1
  store ptr %p1, ptr %l1
  store i64 %p2, ptr %l2
  br label %bb0
bb0:
  %t0 = load i64, ptr %l2
  %t1 = load i64, ptr @"static std.stringbuilder.CONTINUATION_FIRST"
  %t2 = icmp sge i64 %t0, %t1
  %t3 = zext i1 %t2 to i8
  store i8 %t3, ptr %l4
  %t4 = load i8, ptr %l4
  %t5 = icmp ne i8 %t4, 0
  br i1 %t5, label %bb2, label %bb3
bb1:
  %t6 = load i8, ptr %l3
  store i8 %t6, ptr %l0
  %t7 = load i8, ptr %l0
  ret i8 %t7
bb2:
  %t8 = load i64, ptr %l2
  %t9 = load i64, ptr @"static std.stringbuilder.CONTINUATION_END"
  %t10 = icmp slt i64 %t8, %t9
  %t11 = zext i1 %t10 to i8
  store i8 %t11, ptr %l5
  %t12 = load i8, ptr %l5
  store i8 %t12, ptr %l3
  br label %bb1
bb3:
  store i8 0, ptr %l3
  br label %bb1
}

define internal void @"saw std.stringbuilder.StringBuilder.place_byte(b: Int)"(ptr noalias %p1, i64 %p2) #0 {
entry:
  %l0 = alloca [0 x i8], align 1
  %l1 = alloca ptr, align 8
  %l2 = alloca i64, align 8
  %l3 = alloca i8, align 1
  %l4 = alloca i64, align 8
  %l5 = alloca i64, align 8
  %l6 = alloca i8, align 1
  %l7 = alloca ptr, align 8
  %l8 = alloca ptr, align 8
  %l9 = alloca i64, align 8
  %l10 = alloca i8, align 1
  %l11 = alloca i64, align 8
  %l12 = alloca i64, align 8
  store ptr %p1, ptr %l1
  store i64 %p2, ptr %l2
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = getelementptr i8, ptr %t0, i64 32
  %t2 = load i8, ptr %t1
  %t3 = icmp ne i8 %t2, 0
  br i1 %t3, label %bb3, label %bb4
bb1:
  %t4 = load ptr, ptr %l1
  %t5 = load i8, ptr %t4
  %t6 = zext i8 %t5 to i64
  switch i64 %t6, label %nocase.0 [ i64 1, label %bb9 i64 0, label %bb10 ]
nocase.0:
  unreachable
bb2:
  %t7 = load i8, ptr %l3
  %t8 = icmp ne i8 %t7, 0
  br i1 %t8, label %bb5, label %bb6
bb3:
  %t9 = load ptr, ptr %l1
  %t10 = getelementptr i8, ptr %t9, i64 16
  %t11 = load i64, ptr %t10
  %t12 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t11, i64 2)
  %t13 = extractvalue { i64, i1 } %t12, 0
  %t14 = extractvalue { i64, i1 } %t12, 1
  br i1 %t14, label %check.1, label %checked.2
check.1:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 284)
  unreachable
checked.2:
  store i64 %t13, ptr %l4
  %t15 = load ptr, ptr %l1
  %t16 = getelementptr i8, ptr %t15, i64 24
  %t17 = load i64, ptr %t16
  %t18 = load i64, ptr @"static std.stringbuilder.MARKER_LEN"
  %t19 = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %t17, i64 %t18)
  %t20 = extractvalue { i64, i1 } %t19, 0
  %t21 = extractvalue { i64, i1 } %t19, 1
  br i1 %t21, label %check.3, label %checked.4
check.3:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 284)
  unreachable
checked.4:
  store i64 %t20, ptr %l5
  %t22 = load i64, ptr %l4
  %t23 = load i64, ptr %l5
  %t24 = icmp sgt i64 %t22, %t23
  %t25 = zext i1 %t24 to i8
  store i8 %t25, ptr %l6
  %t26 = load i8, ptr %l6
  store i8 %t26, ptr %l3
  br label %bb2
bb4:
  store i8 0, ptr %l3
  br label %bb2
bb5:
  %t27 = load ptr, ptr %l1
  store ptr %t27, ptr %l7
  %t28 = load ptr, ptr %l7
  call void @"saw std.stringbuilder.StringBuilder.mark_truncated()"(ptr %t28)
  br label %bb7
bb6:
  br label %bb1
bb7:
  ret void
bb8:
  ret void
bb9:
  %t29 = load ptr, ptr %l1
  %t30 = getelementptr i8, ptr %t29, i64 8
  %t31 = load ptr, ptr %t30
  store ptr %t31, ptr %l8
  %t32 = load ptr, ptr %l1
  %t33 = getelementptr i8, ptr %t32, i64 16
  %t34 = load i64, ptr %t33
  store i64 %t34, ptr %l9
  %t35 = load i64, ptr %l2
  %t36 = trunc i64 %t35 to i8
  store i8 %t36, ptr %l10
  %t37 = load ptr, ptr %l8
  %t38 = load i64, ptr %l9
  %t39 = mul i64 %t38, 1
  %t40 = getelementptr i8, ptr %t37, i64 %t39
  %t41 = load i8, ptr %l10
  store i8 %t41, ptr %t40
  %t42 = load ptr, ptr %l1
  %t43 = getelementptr i8, ptr %t42, i64 16
  %t44 = load i64, ptr %t43
  %t45 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t44, i64 1)
  %t46 = extractvalue { i64, i1 } %t45, 0
  %t47 = extractvalue { i64, i1 } %t45, 1
  br i1 %t47, label %check.5, label %checked.6
check.5:
  call void @__saw_fail_overflow(ptr @.bytes.5, i64 17, i64 290)
  unreachable
checked.6:
  store i64 %t46, ptr %l11
  %t48 = load ptr, ptr %l1
  %t49 = getelementptr i8, ptr %t48, i64 16
  %t50 = load i64, ptr %l11
  store i64 %t50, ptr %t49
  %t51 = load ptr, ptr %l1
  %t52 = getelementptr i8, ptr %t51, i64 16
  %t53 = load i64, ptr %t52
  store i64 %t53, ptr %l12
  %t54 = load ptr, ptr %l8
  %t55 = load i64, ptr %l12
  %t56 = mul i64 %t55, 1
  %t57 = getelementptr i8, ptr %t54, i64 %t56
  store i8 0, ptr %t57
  br label %bb8
bb10:
  br label %bb8
}

@__saw_argc = internal global i32 0
@__saw_argv = internal global ptr null

define i32 @__saw_rt_get_argc() #0 {
  %v = load i32, ptr @__saw_argc
  ret i32 %v
}

define ptr @__saw_rt_get_argv() #0 {
  %v = load ptr, ptr @__saw_argv
  ret ptr %v
}

define i32 @main(i32 %argc, ptr %argv) #0 {
entry:
  store i32 %argc, ptr @__saw_argc
  store ptr %argv, ptr @__saw_argv
  call void @"saw hello.main()"()
  ret i32 0
}

define internal i64 @__saw_render_uint(ptr %out, i64 %v) #0 {
entry:
  %tmp = alloca [24 x i8], align 1
  br label %loop
loop:
  %n = phi i64 [ %v, %entry ], [ %q, %loop ]
  %i = phi i64 [ 24, %entry ], [ %i1, %loop ]
  %q = udiv i64 %n, 10
  %r = urem i64 %n, 10
  %d = trunc i64 %r to i8
  %c = add i8 %d, 48
  %i1 = sub i64 %i, 1
  %p = getelementptr i8, ptr %tmp, i64 %i1
  store i8 %c, ptr %p
  %more = icmp ne i64 %q, 0
  br i1 %more, label %loop, label %done
done:
  %len = sub i64 24, %i1
  %src = getelementptr i8, ptr %tmp, i64 %i1
  call void @llvm.memcpy.p0.p0.i64(ptr %out, ptr %src, i64 %len, i1 false)
  ret i64 %len
}

define internal i64 @__saw_render_int(ptr %out, i64 %v) #0 {
entry:
  %neg = icmp slt i64 %v, 0
  br i1 %neg, label %minus, label %plain
minus:
  store i8 45, ptr %out
  %mag = sub i64 0, %v
  %rest = getelementptr i8, ptr %out, i64 1
  %n = call i64 @__saw_render_uint(ptr %rest, i64 %mag)
  %len = add i64 %n, 1
  ret i64 %len
plain:
  %m = call i64 @__saw_render_uint(ptr %out, i64 %v)
  ret i64 %m
}

define internal i64 @__saw_append(ptr %buf, i64 %pos, ptr %src, i64 %len) #0 {
entry:
  %closed = icmp slt i64 %pos, 0
  br i1 %closed, label %keep, label %open
keep:
  ret i64 %pos
open:
  %room = sub i64 508, %pos
  %fits = icmp ule i64 %len, %room
  br i1 %fits, label %whole, label %back
whole:
  %at = getelementptr i8, ptr %buf, i64 %pos
  call void @llvm.memcpy.p0.p0.i64(ptr %at, ptr %src, i64 %len, i1 false)
  %end = add i64 %pos, %len
  ret i64 %end
back:
  %n = phi i64 [ %room, %open ], [ %n1, %step ]
  %none = icmp eq i64 %n, 0
  br i1 %none, label %cut, label %test
test:
  %p = getelementptr i8, ptr %src, i64 %n
  %b = load i8, ptr %p
  %hi = and i8 %b, -64
  %inside = icmp eq i8 %hi, -128
  br i1 %inside, label %step, label %cut
step:
  %n1 = sub i64 %n, 1
  br label %back
cut:
  %at2 = getelementptr i8, ptr %buf, i64 %pos
  call void @llvm.memcpy.p0.p0.i64(ptr %at2, ptr %src, i64 %n, i1 false)
  %stop = add i64 %pos, %n
  %shut = sub i64 -1, %stop
  ret i64 %shut
}

define internal i64 @__saw_finish(ptr %buf, i64 %pos) #0 {
entry:
  %cut = icmp slt i64 %pos, 0
  br i1 %cut, label %mark, label %line
mark:
  %stop = sub i64 -1, %pos
  %m0 = getelementptr i8, ptr %buf, i64 %stop
  store i8 -30, ptr %m0
  %m1 = getelementptr i8, ptr %m0, i64 1
  store i8 -128, ptr %m1
  %m2 = getelementptr i8, ptr %m0, i64 2
  store i8 -90, ptr %m2
  %marked = add i64 %stop, 3
  br label %line
line:
  %end = phi i64 [ %marked, %mark ], [ %pos, %entry ]
  %nl = getelementptr i8, ptr %buf, i64 %end
  store i8 10, ptr %nl
  %total = add i64 %end, 1
  ret i64 %total
}

define internal i64 @__saw_append_int(ptr %buf, i64 %pos, i64 %v) #0 {
entry:
  %tmp = alloca [24 x i8], align 1
  %n = call i64 @__saw_render_int(ptr %tmp, i64 %v)
  %end = call i64 @__saw_append(ptr %buf, i64 %pos, ptr %tmp, i64 %n)
  ret i64 %end
}

define internal i64 @__saw_append_uint(ptr %buf, i64 %pos, i64 %v) #0 {
entry:
  %tmp = alloca [24 x i8], align 1
  %n = call i64 @__saw_render_uint(ptr %tmp, i64 %v)
  %end = call i64 @__saw_append(ptr %buf, i64 %pos, ptr %tmp, i64 %n)
  ret i64 %end
}

@__saw_fail_at = private unnamed_addr constant [9 x i8] c"panic at "
@__saw_fail_colon = private unnamed_addr constant [2 x i8] c": "
@__saw_fail_true = private unnamed_addr constant [4 x i8] c"true"
@__saw_fail_false = private unnamed_addr constant [5 x i8] c"false"
@__saw_fail_overflow.reason = private unnamed_addr constant [16 x i8] c"integer overflow"
@__saw_fail_divide.reason = private unnamed_addr constant [16 x i8] c"division by zero"
@__saw_fail_shift.reason = private unnamed_addr constant [18 x i8] c"shift out of range"
@__saw_fail_unwrap.reason = private unnamed_addr constant [20 x i8] c"force unwrap of None"
@__saw_fail_try.reason = private unnamed_addr constant [11 x i8] c"try! failed"

define internal i64 @__saw_fail_head(ptr %buf, ptr %file, i64 %file_len, i64 %line) #0 {
entry:
  %at = call i64 @__saw_append(ptr %buf, i64 0, ptr @__saw_fail_at, i64 9)
  %named = call i64 @__saw_append(ptr %buf, i64 %at, ptr %file, i64 %file_len)
  %known = icmp sge i64 %line, 0
  br i1 %known, label %number, label %tail
number:
  %colon = call i64 @__saw_append(ptr %buf, i64 %named, ptr @__saw_fail_colon, i64 1)
  %lined = call i64 @__saw_append_uint(ptr %buf, i64 %colon, i64 %line)
  br label %tail
tail:
  %pos = phi i64 [ %named, %entry ], [ %lined, %number ]
  %end = call i64 @__saw_append(ptr %buf, i64 %pos, ptr @__saw_fail_colon, i64 2)
  ret i64 %end
}

define internal void @__saw_fail(ptr %file, i64 %file_len, i64 %line, ptr %text, i64 %text_len) noinline noreturn #0 {
entry:
  %buf = alloca [512 x i8], align 1
  %head = call i64 @__saw_fail_head(ptr %buf, ptr %file, i64 %file_len, i64 %line)
  %done = call i64 @__saw_append(ptr %buf, i64 %head, ptr %text, i64 %text_len)
  %end = call i64 @__saw_finish(ptr %buf, i64 %done)
  call void @"saw std.panic.panic_sink(message: UnsafePointer<Int8>, length: Int)"(ptr %buf, i64 %end)
  unreachable
}

define internal void @__saw_fail_signed(ptr %file, i64 %file_len, i64 %line, ptr %text, i64 %text_len, i64 %v) noinline noreturn #0 {
entry:
  %buf = alloca [512 x i8], align 1
  %head = call i64 @__saw_fail_head(ptr %buf, ptr %file, i64 %file_len, i64 %line)
  %pos = call i64 @__saw_append(ptr %buf, i64 %head, ptr %text, i64 %text_len)
  %done = call i64 @__saw_append_int(ptr %buf, i64 %pos, i64 %v)
  %end = call i64 @__saw_finish(ptr %buf, i64 %done)
  call void @"saw std.panic.panic_sink(message: UnsafePointer<Int8>, length: Int)"(ptr %buf, i64 %end)
  unreachable
}

define internal void @__saw_fail_unsigned(ptr %file, i64 %file_len, i64 %line, ptr %text, i64 %text_len, i64 %v) noinline noreturn #0 {
entry:
  %buf = alloca [512 x i8], align 1
  %head = call i64 @__saw_fail_head(ptr %buf, ptr %file, i64 %file_len, i64 %line)
  %pos = call i64 @__saw_append(ptr %buf, i64 %head, ptr %text, i64 %text_len)
  %done = call i64 @__saw_append_uint(ptr %buf, i64 %pos, i64 %v)
  %end = call i64 @__saw_finish(ptr %buf, i64 %done)
  call void @"saw std.panic.panic_sink(message: UnsafePointer<Int8>, length: Int)"(ptr %buf, i64 %end)
  unreachable
}

define internal void @__saw_fail_parts(ptr %file, i64 %file_len, i64 %line, ptr %text, i64 %text_len, ptr %parts, i64 %count) noinline noreturn #0 {
entry:
  %buf = alloca [512 x i8], align 1
  %head = call i64 @__saw_fail_head(ptr %buf, ptr %file, i64 %file_len, i64 %line)
  %pos = call i64 @__saw_append(ptr %buf, i64 %head, ptr %text, i64 %text_len)
  br label %loop
loop:
  %i = phi i64 [ 0, %entry ], [ %i1, %next ]
  %at = phi i64 [ %pos, %entry ], [ %after, %next ]
  %more = icmp slt i64 %i, %count
  br i1 %more, label %part, label %last
part:
  %offset = mul i64 %i, 24
  %p = getelementptr i8, ptr %parts, i64 %offset
  %kind = load i64, ptr %p
  %first = getelementptr i8, ptr %p, i64 8
  %second = getelementptr i8, ptr %p, i64 16
  switch i64 %kind, label %run [ i64 1, label %signed i64 2, label %unsigned i64 3, label %bool ]
run:
  %src = load ptr, ptr %first
  %len = load i64, ptr %second
  %ran = call i64 @__saw_append(ptr %buf, i64 %at, ptr %src, i64 %len)
  br label %next
signed:
  %sv = load i64, ptr %first
  %sd = call i64 @__saw_append_int(ptr %buf, i64 %at, i64 %sv)
  br label %next
unsigned:
  %uv = load i64, ptr %first
  %ud = call i64 @__saw_append_uint(ptr %buf, i64 %at, i64 %uv)
  br label %next
bool:
  %byte = load i8, ptr %first
  %yes = icmp ne i8 %byte, 0
  %word = select i1 %yes, ptr @__saw_fail_true, ptr @__saw_fail_false
  %size = select i1 %yes, i64 4, i64 5
  %bd = call i64 @__saw_append(ptr %buf, i64 %at, ptr %word, i64 %size)
  br label %next
next:
  %after = phi i64 [ %ran, %run ], [ %sd, %signed ], [ %ud, %unsigned ], [ %bd, %bool ]
  %i1 = add i64 %i, 1
  br label %loop
last:
  %done = phi i64 [ %at, %loop ]
  %end = call i64 @__saw_finish(ptr %buf, i64 %done)
  call void @"saw std.panic.panic_sink(message: UnsafePointer<Int8>, length: Int)"(ptr %buf, i64 %end)
  unreachable
}

define internal void @__saw_fail_overflow(ptr %file, i64 %file_len, i64 %line) noinline noreturn #0 {
entry:
  call void @__saw_fail(ptr %file, i64 %file_len, i64 %line, ptr @__saw_fail_overflow.reason, i64 16)
  unreachable
}

define internal void @__saw_fail_divide(ptr %file, i64 %file_len, i64 %line) noinline noreturn #0 {
entry:
  call void @__saw_fail(ptr %file, i64 %file_len, i64 %line, ptr @__saw_fail_divide.reason, i64 16)
  unreachable
}

define internal void @__saw_fail_shift(ptr %file, i64 %file_len, i64 %line) noinline noreturn #0 {
entry:
  call void @__saw_fail(ptr %file, i64 %file_len, i64 %line, ptr @__saw_fail_shift.reason, i64 18)
  unreachable
}

define internal void @__saw_fail_unwrap(ptr %file, i64 %file_len, i64 %line) noinline noreturn #0 {
entry:
  call void @__saw_fail(ptr %file, i64 %file_len, i64 %line, ptr @__saw_fail_unwrap.reason, i64 20)
  unreachable
}

define internal void @__saw_fail_try(ptr %file, i64 %file_len, i64 %line) noinline noreturn #0 {
entry:
  call void @__saw_fail(ptr %file, i64 %file_len, i64 %line, ptr @__saw_fail_try.reason, i64 11)
  unreachable
}

define internal void @__saw_fail_print(ptr %file, i64 %file_len, i64 %line, i64 %status) noinline noreturn #0 {
entry:
  %cause = alloca [512 x i8], align 1
  %n = call i64 @"saw std.panic.print_failure(status: Int, bytes: UnsafePointer<Int8>, capacity: Int)"(i64 %status, ptr %cause, i64 512)
  call void @__saw_fail(ptr %file, i64 %file_len, i64 %line, ptr %cause, i64 %n)
  unreachable
}

attributes #0 = { "frame-pointer"="non-leaf" }
