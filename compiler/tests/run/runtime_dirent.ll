; sawc link manifest
; target arm64-apple-darwin
; speed -O2
; runtime none

target triple = "arm64-apple-macosx11.0.0"

@"static dirent.DIRENT_NAME_OFFSET" = internal global i64 21
@"static std.panic.PANIC_REPORT" = internal global i64 0, align 8
@"static std.panic.PANIC_REPORTING" = internal global i64 0, align 8
@"static std.string.LENGTH_SLOT" = internal global i64 -1

declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)
declare void @__saw_rt_panic(ptr, i64)

define ptr @"__saw_rt_fs_dirent_name"(ptr %p1) #0 {
entry:
  %l0 = alloca ptr, align 8
  %l1 = alloca ptr, align 8
  %l2 = alloca ptr, align 8
  store ptr %p1, ptr %l1
  br label %bb0
bb0:
  %t0 = load ptr, ptr %l1
  %t1 = load i64, ptr @"static dirent.DIRENT_NAME_OFFSET"
  %t2 = mul i64 %t1, 1
  %t3 = getelementptr i8, ptr %t0, i64 %t2
  store ptr %t3, ptr %l2
  %t4 = load ptr, ptr %l2
  store ptr %t4, ptr %l0
  %t5 = load ptr, ptr %l0
  ret ptr %t5
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

attributes #0 = { "frame-pointer"="non-leaf" }
