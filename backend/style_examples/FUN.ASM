dosseg
.model small
.data
msg1 db "enter first number x",10,13,"$"
msg2 db "enter second number y",10,13,"$"
.code
mov ax,@data
mov ds,ax

mov ah,9
mov dx,offset msg1
int 21h

mov ah,1
int 21h

sub al,30h

mov bl,al

mov ah,9
mov dx,offset msg2
int 21h

mov ah,1
int 21h
sub al,30h
mov bh,al
mov al,2
mov ah,0
mul bl

add bh,al
mov ah,2
add bh,30h
mov dl,bh
int 21h

mov ah,4ch
int 21h
end
